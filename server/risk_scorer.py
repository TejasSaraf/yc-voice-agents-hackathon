"""FreightVoice Predictive Risk Intelligence Layer.

XGBoost-style weighted risk score (0–100) combining five signals after every
carrier check-in call:

  Signal 1 — Voice Sentiment   (30%)  Leading indicator. The unique moat.
                                       Classified by the LLM from driver tone.
  Signal 2 — Historical OTD    (20%)  Carrier's on-time rate on this lane.
  Signal 3 — Time Pressure     (20%)  Buffer between driver's ETA and deadline.
  Signal 4 — Weather on Route  (15%)  NOAA API, async, 3-second hard timeout.
  Signal 5 — ETA Vagueness     (15%)  Concrete number vs. vague / no ETA.

Score produced by a sigmoid centred at 0.45:
    risk_score = 100 / (1 + exp(-6 × (raw − 0.45)))

Action thresholds
    0–40   MONITOR   — log confirmation, next check-in in 2 hours
    41–70  WARNING   — alert logistics team, follow-up call in 30 minutes
    71–100 CRITICAL  — immediate alert + dock hold + backup carrier search
"""

import asyncio
from dataclasses import dataclass, field
from math import exp
from enum import Enum

import aiohttp
from loguru import logger


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

#: Maps driver tone labels (from the LLM) to a 0.0–1.0 risk contribution.
SENTIMENT_SCORES: dict[str, float] = {
    "confident": 0.05,   # "I'll be there at 2pm, no issues"
    "calm":      0.20,   # "Yeah about 20 out, everything's fine"
    "uncertain": 0.60,   # "I think... maybe around 3? There's some weather stuff"
    "frustrated":0.80,   # "Man I don't know, been sitting here for hours..."
}


# ---------------------------------------------------------------------------
# Risk levels and result types
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    MONITOR  = "MONITOR"
    WARNING  = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class SignalBreakdown:
    label: str
    raw_value: float
    weight: float
    contribution: float


@dataclass
class RiskResult:
    score: int                              # 0–100, post-sigmoid
    level: RiskLevel
    raw_score: float                        # pre-sigmoid weighted sum
    signals: dict[str, SignalBreakdown] = field(default_factory=dict)
    recommended_action: str = ""
    next_checkin_minutes: int = 120         # 120 / 30 / 0


# ---------------------------------------------------------------------------
# NOAA weather fetch
# ---------------------------------------------------------------------------

#: Approximate route midpoints used for NOAA weather lookup.
_LANE_COORDS: dict[str, tuple[float, float]] = {
    "Reno, NV → Austin, TX (I-80 / I-35)":               (39.5, -106.0),
    "Port of LA, CA → Detroit, MI (I-10 / I-44 / I-70)": (38.0,  -95.0),
    "Monterrey, MX → Dearborn, MI (I-35 / I-69)":        (33.0,  -96.0),
    "Portland, OR → Everett, WA (I-5)":                   (47.0, -122.3),
    "Spokane, WA → Renton, WA (I-90)":                    (47.4, -121.5),
    "Monterrey, MX → Austin, TX (I-35)":                  (28.0,  -99.0),
    "Indianapolis, IN → East Peoria, IL (I-74)":          (40.0,  -87.5),
    "Rockford, IL → Waterloo, IA (US-20)":                (42.0,  -91.5),
    "Cedar Rapids, IA → Dubuque, IA (US-151)":            (42.3,  -91.0),
    "Phoenix, AZ → Chandler, AZ (Loop 202)":              (33.3, -111.9),
    "Columbus, OH → Normal, IL (I-70 / I-74)":            (40.0,  -86.0),
    "Sparks, NV → Fremont, CA (I-80)":                    (39.5, -120.5),
}

#: NOAA shortForecast keyword → risk float. Ordered most-severe first.
_WEATHER_KEYWORDS: list[tuple[str, float]] = [
    ("blizzard",     0.90),
    ("freezing",     0.90),
    ("sleet",        0.90),
    ("ice",          0.90),
    ("snow",         0.90),
    ("thunderstorm", 0.50),
    ("thunder",      0.50),
    ("fog",          0.50),
    ("rain",         0.50),
    ("drizzle",      0.50),
    ("shower",       0.50),
    ("sunny",        0.10),
    ("clear",        0.10),
    ("fair",         0.10),
]


async def fetch_weather_risk(lane: str, timeout: float = 3.0) -> float:
    """Return a weather risk float (0.10–0.90) from the NOAA API.

    The call is hard-capped at ``timeout`` seconds so it never stalls the
    voice pipeline.  Falls back to 0.20 on any error, timeout, or missing
    lane coordinates.

    Args:
        lane: The load's ``lane`` string (must match a key in ``_LANE_COORDS``).
        timeout: Hard timeout in seconds for the entire NOAA round-trip.

    Returns:
        Weather risk contribution (0.10 = clear, 0.50 = rain/fog,
        0.90 = snow/ice, 0.20 = unknown/timeout).
    """
    coords = _LANE_COORDS.get(lane)
    if not coords:
        logger.debug(f"No route coords for '{lane}' — weather defaulting to 0.20")
        return 0.20

    lat, lon = coords
    points_url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"

    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(points_url) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"NOAA /points HTTP {resp.status} for '{lane}'"
                    )
                    return 0.20
                points_data = await resp.json()

            forecast_url = (
                points_data.get("properties", {}).get("forecast", "")
            )
            if not forecast_url:
                return 0.20

            async with session.get(forecast_url) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"NOAA /forecast HTTP {resp.status} for '{lane}'"
                    )
                    return 0.20
                forecast_data = await resp.json()

        periods = forecast_data.get("properties", {}).get("periods", [])
        if not periods:
            return 0.20

        short_forecast = periods[0].get("shortForecast", "").lower()
        for keyword, risk in _WEATHER_KEYWORDS:
            if keyword in short_forecast:
                logger.info(
                    f"NOAA '{lane}': '{short_forecast}' → weather_risk={risk}"
                )
                return risk

        # No alarm keyword found — treat as clear.
        logger.info(
            f"NOAA '{lane}': '{short_forecast}' — no match, weather_risk=0.10"
        )
        return 0.10

    except asyncio.TimeoutError:
        logger.warning(
            f"NOAA timeout after {timeout}s for '{lane}' — defaulting to 0.20"
        )
        return 0.20
    except Exception as exc:
        logger.warning(f"NOAA error for '{lane}': {exc} — defaulting to 0.20")
        return 0.20


# ---------------------------------------------------------------------------
# Sigmoid helper
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    """Sigmoid centred at 0.45 with steepness 6, output 0–100.

    Keeps scores away from the extreme edges so that 50 ≈ genuine
    uncertainty, <20 ≈ clean load, and >80 ≈ real danger.
    """
    return 100.0 / (1.0 + exp(-6.0 * (x - 0.45)))


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------

def compute_risk_score(
    *,
    sentiment: str,
    historical_otd_rate: float,
    eta_minutes_from_now: int | None,
    deadline_minutes_from_now: int | None,
    weather_risk: float,
    hourly_downtime_cost: int = 0,
    production_line: str = "the production line",
    load_id: str = "",
) -> RiskResult:
    """Compute FreightVoice's predictive risk score (0–100).

    All keyword-only arguments keep call sites explicit and prevent
    accidental positional mis-ordering.

    Args:
        sentiment: Driver tone classified by the LLM.
            One of "confident" | "calm" | "uncertain" | "frustrated".
            Unknown labels map to 0.40.
        historical_otd_rate: Carrier's on-time-delivery rate on this lane
            (0.0–1.0).  74% OTD → 0.26 risk contribution.
        eta_minutes_from_now: Minutes until the driver says they'll arrive.
            None if the driver gave no concrete ETA.
        deadline_minutes_from_now: Minutes until the dock appointment.
            None if the appointment time could not be parsed.
        weather_risk: Pre-fetched NOAA risk float (call ``fetch_weather_risk``
            before this function).
        hourly_downtime_cost: USD/hr the production line loses on stoppage.
            Used only in the recommended-action text.
        production_line: Line name string — used in recommended-action text.
        load_id: Load identifier — used in log output.

    Returns:
        :class:`RiskResult` with score, level, signal breakdown, and action.
    """

    # -- Signal 1: Voice sentiment (30%) ------------------------------------
    sentiment_key = sentiment.lower().strip()
    sentiment_score = SENTIMENT_SCORES.get(sentiment_key, 0.40)

    # -- Signal 2: Historical on-time rate (20%) ----------------------------
    historical_risk = round(1.0 - max(0.0, min(1.0, historical_otd_rate)), 4)

    # -- Signal 3: Time pressure (20%) ------------------------------------
    if eta_minutes_from_now is None or deadline_minutes_from_now is None:
        time_pressure = 0.65
        buffer_label = "no ETA"
    else:
        buffer_minutes = deadline_minutes_from_now - eta_minutes_from_now
        if buffer_minutes >= 60:
            time_pressure = 0.10
        elif buffer_minutes >= 0:
            # Linear ramp: 60-min buffer → 0.10, 0-min buffer → 0.70
            time_pressure = 0.10 + (60 - buffer_minutes) / 60.0 * 0.60
        else:
            time_pressure = 1.0   # already past deadline
        buffer_label = f"{buffer_minutes}min buffer"

    # -- Signal 4: Weather on route (15%) — passed in -----------------------
    # (caller runs fetch_weather_risk() async before calling this function)

    # -- Signal 5: ETA vagueness (15%) -------------------------------------
    eta_vagueness = 0.70 if eta_minutes_from_now is None else 0.10
    vagueness_label = "no ETA given" if eta_minutes_from_now is None else "ETA confirmed"

    # -- Weighted sum -------------------------------------------------------
    raw_score = (
        sentiment_score  * 0.30
        + historical_risk  * 0.20
        + time_pressure    * 0.20
        + weather_risk     * 0.15
        + eta_vagueness    * 0.15
    )
    risk_score = int(_sigmoid(raw_score))

    # -- Risk level & next check-in ----------------------------------------
    if risk_score <= 40:
        level = RiskLevel.MONITOR
        next_checkin = 120
    elif risk_score <= 70:
        level = RiskLevel.WARNING
        next_checkin = 30
    else:
        level = RiskLevel.CRITICAL
        next_checkin = 0

    # -- Human-readable action ---------------------------------------------
    cost_str = (
        f"${hourly_downtime_cost / 1_000_000:.1f}M/hr"
        if hourly_downtime_cost >= 1_000_000
        else f"${hourly_downtime_cost / 1_000:.0f}K/hr"
    )
    if level == RiskLevel.CRITICAL:
        recommended_action = (
            f"CRITICAL — {production_line} at immediate risk "
            f"(downtime costs {cost_str}). "
            "Alert production team now. Initiate outbound call to carrier. "
            "Begin backup-carrier search. Hold dock team on standby."
        )
    elif level == RiskLevel.WARNING:
        recommended_action = (
            f"WARNING — {production_line} showing elevated risk "
            f"(downtime costs {cost_str}). "
            f"Alert logistics team. Schedule follow-up call in {next_checkin} minutes. "
            "Confirm backup carrier is on standby."
        )
    else:
        recommended_action = (
            f"MONITOR — {production_line} appears on track. "
            f"Log confirmation. Next automated check-in in {next_checkin} minutes."
        )

    # -- Signal breakdown for audit trail ----------------------------------
    signals: dict[str, SignalBreakdown] = {
        "voice_sentiment": SignalBreakdown(
            label=sentiment_key,
            raw_value=round(sentiment_score, 4),
            weight=0.30,
            contribution=round(sentiment_score * 0.30, 4),
        ),
        "historical_otd": SignalBreakdown(
            label=f"{int(historical_otd_rate * 100)}% OTD on lane",
            raw_value=historical_risk,
            weight=0.20,
            contribution=round(historical_risk * 0.20, 4),
        ),
        "time_pressure": SignalBreakdown(
            label=buffer_label,
            raw_value=round(time_pressure, 4),
            weight=0.20,
            contribution=round(time_pressure * 0.20, 4),
        ),
        "weather_risk": SignalBreakdown(
            label=f"NOAA route risk {weather_risk}",
            raw_value=weather_risk,
            weight=0.15,
            contribution=round(weather_risk * 0.15, 4),
        ),
        "eta_vagueness": SignalBreakdown(
            label=vagueness_label,
            raw_value=eta_vagueness,
            weight=0.15,
            contribution=round(eta_vagueness * 0.15, 4),
        ),
    }

    logger.info(
        f"🎯 RISK SCORE {load_id} [{level.value}] {risk_score}/100  "
        f"raw={raw_score:.4f}  "
        f"sentiment={sentiment_key}({sentiment_score})  "
        f"otd={historical_otd_rate}  "
        f"pressure={time_pressure:.2f}  "
        f"weather={weather_risk}  "
        f"vagueness={eta_vagueness}"
    )

    return RiskResult(
        score=risk_score,
        level=level,
        raw_score=round(raw_score, 4),
        signals=signals,
        recommended_action=recommended_action,
        next_checkin_minutes=next_checkin,
    )
