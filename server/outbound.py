"""FreightVoice outbound call engine.

Every outbound call is tied to a specific load record.  FreightVoice never
dials a random number — the phone number is pulled from the load tender that
the carrier already signed, so the call is contractually grounded.

Six triggers
────────────
  SCHEDULED        Every N hours per active load (default: 2 h)
  RISK_THRESHOLD   Risk score recalculates and crosses 60
  EXTERNAL_SIGNAL  NOAA storm / Google Maps traffic alert on route
  MISSED_MILESTONE Carrier didn't confirm departure/checkpoint on time
  INBOUND          Carrier called us first — no outbound needed
  DASHBOARD        Shipper clicked "Call now" in the UI

Demo mode
─────────
Set DEMO_CARRIER_PHONE in .env to your own cell.  ALL outbound calls route
to that number so you can play the driver yourself during the demo.
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import aiohttp
from dotenv import load_dotenv
from loguru import logger

from freight_backend import SHIPMENTS
from freight_scenarios import _appointment_minutes_from_now
from risk_scorer import compute_risk_score, fetch_weather_risk

load_dotenv(override=True)


# ---------------------------------------------------------------------------
# Trigger taxonomy
# ---------------------------------------------------------------------------

class CallTrigger(str, Enum):
    SCHEDULED        = "scheduled"
    RISK_THRESHOLD   = "risk_threshold"
    EXTERNAL_SIGNAL  = "external_signal"
    MISSED_MILESTONE = "missed_milestone"
    INBOUND          = "inbound"          # informational — no outbound fires
    DASHBOARD        = "dashboard"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class CallResult:
    ok: bool
    load_id: str
    trigger: CallTrigger
    call_sid: str = ""
    to: str = ""
    demo: bool = False
    message: str = ""
    ts: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "load_id": self.load_id,
            "trigger": self.trigger.value,
            "call_sid": self.call_sid,
            "to": self.to,
            "demo": self.demo,
            "message": self.message,
            "ts": self.ts,
        }


# ---------------------------------------------------------------------------
# Phone number resolution
# ---------------------------------------------------------------------------

def _resolve_phone(load_id: str) -> tuple[str, bool]:
    """Return (phone_number, is_demo).

    Priority:
      1. DEMO_CARRIER_PHONE in .env  →  demo mode, always your cell
      2. load["driver_phone"]        →  production, number from load tender
    """
    demo_phone = os.getenv("DEMO_CARRIER_PHONE", "").strip()
    if demo_phone:
        return demo_phone, True

    shipment = SHIPMENTS.get(load_id, {})
    driver_phone = shipment.get("driver_phone", "")
    if not driver_phone:
        raise ValueError(f"No phone number on load '{load_id}' and DEMO_CARRIER_PHONE not set")
    return driver_phone, False


# ---------------------------------------------------------------------------
# TwiML builder
# ---------------------------------------------------------------------------

def _pipecat_ws_url(load_id: str, trigger: CallTrigger, inbound: bool = False) -> str | None:
    """Return the WebSocket URL that Twilio should stream audio to, or None.

    Resolution order:
      1. PIPECAT_WS_URL  — local dev via ngrok
                           e.g. wss://abc123.ngrok.io/ws
      2. PIPECAT_ORG_NAME — Pipecat Cloud
                           → wss://api.pipecat.daily.co/ws/twilio
      3. None             — no WebSocket configured, use <Say> fallback
    """
    ws_url   = os.getenv("PIPECAT_WS_URL", "").strip()
    pipecat_org = os.getenv("PIPECAT_ORG_NAME", "").strip()

    if ws_url:
        return ws_url          # local dev (ngrok or tunnel)
    if pipecat_org:
        return "wss://api.pipecat.daily.co/ws/twilio"
    return None


def _build_twiml(
    load_id: str,
    trigger: CallTrigger,
    inbound: bool = False,
) -> str:
    """Return TwiML that connects the answered call to the FreightVoice bot.

    Three modes:
      1. PIPECAT_WS_URL set  — local dev via ngrok WebSocket
      2. PIPECAT_ORG_NAME set — Pipecat Cloud production
      3. Neither              — plain <Say> fallback (demo without Pipecat)

    For Pipecat Cloud the TwiML uses <Stream> with Parameter elements that
    Pipecat Cloud reads to select the right bot service and pass load context.
    For a local WebSocket the same <Stream> tag works; load context is passed
    via query parameters on the WebSocket URL (Pipecat reads them from the
    HTTP upgrade headers).

    Args:
        load_id:  Load identifier passed to the bot as context.
        trigger:  Why the call fired (for logging inside the bot).
        inbound:  True when the carrier called us first (Twilio inbound webhook).
                  False when we called the carrier (outbound, carrier answered).
    """
    ws_url = _pipecat_ws_url(load_id, trigger, inbound)
    pipecat_org = os.getenv("PIPECAT_ORG_NAME", "").strip()
    shipment    = SHIPMENTS.get(load_id, {})

    if ws_url:
        if pipecat_org and "pipecat.daily.co" in ws_url:
            # Pipecat Cloud: pass bot service host + env vars as <Parameter> elements
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response><Connect>"
                f'<Stream url="{ws_url}">'
                f'<Parameter name="_pipecatCloudServiceHost" value="freight-bot.{pipecat_org}"/>'
                f'<Parameter name="FREIGHTVOICE_LOAD_ID" value="{load_id}"/>'
                '<Parameter name="FREIGHTVOICE_SCENARIO" value="carrier"/>'
                f'<Parameter name="FREIGHTVOICE_TRIGGER" value="{trigger.value}"/>'
                "</Stream></Connect></Response>"
            )
        else:
            # Local dev / ngrok: pass load context as <Parameter> elements so
            # the WebSocket URL stays clean and we don't have to XML-escape
            # query-string ampersands (Twilio's TwiML parser is strict).
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response><Connect>"
                f'<Stream url="{ws_url}">'
                f'<Parameter name="load" value="{load_id}"/>'
                f'<Parameter name="trigger" value="{trigger.value}"/>'
                '<Parameter name="scenario" value="carrier"/>'
                "</Stream></Connect></Response>"
            )
        logger.info(
            f"TwiML → {'Pipecat Cloud' if pipecat_org else 'local WebSocket'} "
            f"for load={load_id} trigger={trigger.value} inbound={inbound}"
        )
        return xml

    # ── Fallback: plain TTS prompt ────────────────────────────────────────
    # Works without any Pipecat setup — useful for first-run testing.
    driver = shipment.get("driver_name", "driver")
    cargo  = shipment.get("commodity", "your load")
    dock   = shipment.get("dock", "the dock")
    appt   = shipment.get("appointment", "your appointment")
    logger.warning(
        f"Neither PIPECAT_WS_URL nor PIPECAT_ORG_NAME set — "
        f"using plain <Say> fallback for load={load_id}"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say>Hi {driver}, this is FreightVoice calling about your load of {cargo}. "
        f"You are scheduled to deliver to {dock} at {appt}. "
        "Please confirm your current location and estimated arrival time.</Say>"
        "<Pause length='30'/>"
        "</Response>"
    )


# ---------------------------------------------------------------------------
# Core call function
# ---------------------------------------------------------------------------

async def call_carrier(
    load_id: str,
    trigger: CallTrigger,
    *,
    context: str = "",
) -> CallResult:
    """Place a Twilio outbound call to the carrier on ``load_id``.

    The phone number is resolved from the load record (or DEMO_CARRIER_PHONE).
    When answered, Twilio fetches TwiML from BASE_URL/outbound which streams
    audio into the Pipecat FreightVoice bot.

    Args:
        load_id: Load identifier — must exist in SHIPMENTS.
        trigger: Why the call is being made.
        context: Optional free-text note logged alongside the call (e.g.
            "risk_score=72", "NOAA storm on I-35").
    """
    if load_id not in SHIPMENTS:
        return CallResult(
            ok=False, load_id=load_id, trigger=trigger,
            message=f"Unknown load '{load_id}'"
        )

    shipment = SHIPMENTS[load_id]

    try:
        phone, is_demo = _resolve_phone(load_id)
    except ValueError as exc:
        return CallResult(ok=False, load_id=load_id, trigger=trigger, message=str(exc))

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token  = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_PHONE_NUMBER", "").strip()
    base_url    = os.getenv("BASE_URL", "").strip().rstrip("/")

    label = f"{'[DEMO] ' if is_demo else ''}{load_id} → {phone} trigger={trigger.value}"
    if context:
        label += f" ({context})"

    # ── No Twilio creds → dry-run log only ──────────────────────────────
    if not all([account_sid, auth_token, from_number]):
        logger.warning(f"📵 DRY RUN — Twilio not configured. Would call: {label}")
        return CallResult(
            ok=True, load_id=load_id, trigger=trigger,
            to=phone, demo=True,
            call_sid=f"DRY-RUN-{load_id}-{int(datetime.now().timestamp())}",
            message="Dry run — set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER",
        )

    # ── TwiML delivery ────────────────────────────────────────────────────
    # If BASE_URL is set, Twilio fetches TwiML from the /outbound webhook
    # (allows Pipecat streaming). Otherwise inline TwiML via `twiml=` param.
    call_params: dict = {
        "To":      phone,
        "From":    from_number,
        "Timeout": "30",
        "StatusCallback": f"{base_url}/call-status" if base_url else "",
    }

    if base_url:
        call_params["Url"] = (
            f"{base_url}/outbound?load={load_id}&trigger={trigger.value}"
        )
    else:
        call_params["Twiml"] = _build_twiml(load_id, trigger)

    # Remove empty strings so Twilio API doesn't reject them
    call_params = {k: v for k, v in call_params.items() if v}

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                auth=aiohttp.BasicAuth(account_sid, auth_token),
                data=call_params,
            ) as resp:
                data = await resp.json()
                if resp.status not in (200, 201):
                    logger.error(f"Twilio API error {resp.status}: {data}")
                    return CallResult(
                        ok=False, load_id=load_id, trigger=trigger,
                        message=str(data)
                    )

        logger.info(f"📞 CALL PLACED — {label} sid={data['sid']}")
        return CallResult(
            ok=True,
            load_id=load_id,
            trigger=trigger,
            call_sid=data["sid"],
            to=phone,
            demo=is_demo,
            message=f"Call initiated to {shipment['driver_name']} at {shipment['carrier']}",
        )

    except Exception as exc:
        logger.error(f"Twilio call failed for {load_id}: {exc}")
        return CallResult(ok=False, load_id=load_id, trigger=trigger, message=str(exc))


# ---------------------------------------------------------------------------
# Named trigger helpers
# ---------------------------------------------------------------------------

async def risk_triggered_call(load_id: str, new_score: int) -> CallResult | None:
    """Fire a call when risk score crosses the WARNING threshold (60).

    Returns None if below threshold (no call placed).
    """
    if new_score < 60:
        logger.debug(f"Risk score {new_score} for {load_id} below threshold — no call")
        return None
    level = "CRITICAL" if new_score >= 71 else "WARNING"
    logger.info(f"🔴 Risk threshold crossed for {load_id}: score={new_score} [{level}]")
    return await call_carrier(
        load_id,
        CallTrigger.RISK_THRESHOLD,
        context=f"risk_score={new_score} [{level}]",
    )


async def external_signal_call(
    load_id: str,
    signal_type: str,
    description: str,
) -> CallResult:
    """Fire a call because of an external data signal (NOAA / traffic / customs).

    Args:
        signal_type: Short category — "weather", "traffic", "customs", etc.
        description: Human-readable description logged with the call.
    """
    logger.info(f"⚡ External signal for {load_id}: [{signal_type}] {description}")
    return await call_carrier(
        load_id,
        CallTrigger.EXTERNAL_SIGNAL,
        context=f"{signal_type}: {description}",
    )


async def missed_milestone_call(load_id: str, milestone: str) -> CallResult:
    """Fire a call when a carrier misses a required check-in milestone.

    Args:
        milestone: Which milestone was missed, e.g. "departure_confirmation",
            "en_route_checkpoint_1", "30min_out_ping".
    """
    logger.warning(f"⏰ Missed milestone for {load_id}: {milestone}")
    return await call_carrier(
        load_id,
        CallTrigger.MISSED_MILESTONE,
        context=f"missed: {milestone}",
    )


async def dashboard_triggered_call(load_id: str) -> CallResult:
    """Fire a call because the shipper clicked 'Call now' in the dashboard."""
    return await call_carrier(load_id, CallTrigger.DASHBOARD)


# ---------------------------------------------------------------------------
# Scheduled checker — runs in background, every N seconds
# ---------------------------------------------------------------------------

class ScheduledChecker:
    """Async background loop that checks every active load on a fixed interval.

    For each load, it:
      1. Recomputes the risk score with fresh NOAA weather data.
      2. Fires a SCHEDULED call unconditionally (simulates the 2-hour cadence).
      3. Additionally fires a RISK_THRESHOLD call if score ≥ 60.

    In production, reduce check_interval to something like 30–60 minutes and
    only fire calls that are overdue (track last-call timestamps per load).
    For the hackathon demo, set CHECK_INTERVAL_SECONDS=300 (5 min) so you
    can see it fire without waiting 2 hours.
    """

    def __init__(self, check_interval: int | None = None):
        self.interval = check_interval or int(
            os.getenv("CHECK_INTERVAL_SECONDS", str(2 * 60 * 60))
        )
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="scheduled-checker")
        logger.info(
            f"⏱  Scheduled checker started — interval={self.interval}s "
            f"({'demo' if self.interval < 600 else 'production'} mode)"
        )

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            logger.info("⏱  Scheduled checker stopped")

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.interval)
            if not self._running:
                break
            await self._run_checks()

    async def _run_checks(self) -> None:
        logger.info(f"⏱  Running scheduled check for {len(SHIPMENTS)} loads…")
        for load_id, shipment in SHIPMENTS.items():
            try:
                # Recompute risk with fresh weather
                weather_risk = await fetch_weather_risk(shipment["lane"])
                deadline_min = _appointment_minutes_from_now(shipment["appointment"])
                result = compute_risk_score(
                    sentiment="calm",               # pre-call baseline
                    historical_otd_rate=shipment["lane_on_time_rate"],
                    eta_minutes_from_now=None,
                    deadline_minutes_from_now=deadline_min,
                    weather_risk=weather_risk,
                    hourly_downtime_cost=shipment["hourly_downtime_cost"],
                    production_line=shipment["production_line"],
                    load_id=load_id,
                )

                # Always fire a scheduled check call
                await call_carrier(
                    load_id,
                    CallTrigger.SCHEDULED,
                    context=f"score={result.score}",
                )

                # Also fire a risk-threshold call if elevated
                if result.score >= 60:
                    await risk_triggered_call(load_id, result.score)

            except Exception as exc:
                logger.error(f"Scheduled check error for {load_id}: {exc}")

            # Small gap between loads so we don't hammer Twilio all at once
            await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Module-level scheduler instance (shared with api_server.py)
# ---------------------------------------------------------------------------

scheduler = ScheduledChecker()
