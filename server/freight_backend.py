"""Mock backend data for the FreightVoice shipper-side voice agent.

FreightVoice is the inbound-coordination layer for manufacturers (Tesla, John
Deere, Boeing, Apple ...). It calls carriers and suppliers on the shipper's
behalf instead of the logistics team making 80 manual calls a day.

This module holds the demo data. To go live, swap these dicts for calls to a
real TMS / WMS / ERP from inside the tool functions in ``freight_scenarios.py``
— the agent logic doesn't change.

Two scenarios are modeled:

  * SHIPMENTS  — inbound carrier check-in calls (Problems 1 & 2):
                 confirm ETA + dock, verify cargo condition, score delivery
                 risk, and protect the production line.
  * SUPPLIERS  — multilingual supplier compliance calls (Problem 3):
                 confirm pricing under new tariffs, lead times, and docs.

Keys are matched case-insensitively in the bot (load IDs / supplier IDs are
upper-cased before lookup).
"""

# ---------------------------------------------------------------------------
# Scenario 1 & 2 — Inbound carrier check-in / production-line protection
# ---------------------------------------------------------------------------
#
# Each shipment carries everything FreightVoice needs to (a) coordinate dock
# readiness, (b) verify shipper-specific cargo requirements, and (c) score the
# risk to the production line.
#
#   hourly_downtime_cost : USD lost per hour if this line stops for lack of part
#   lane_on_time_rate    : historical on-time % for this carrier on this lane
#   weather_risk         : developing weather event on route (or None)
#   hos_hours_remaining  : driver Hours-of-Service clock remaining
#   requires_sealed      : load must arrive with seal intact
#   requires_temp_control: load is temperature-controlled
SHIPMENTS = {
    "TSLA-BAT-0412": {
        "shipper": "Tesla Austin Gigafactory",
        "carrier": "Sierra Freight Lines",
        "driver_name": "Miguel",
        "commodity": "lithium-ion battery cells",
        "origin": "Reno, Nevada",
        "lane": "Reno, NV → Austin, TX (I-80 / I-35)",
        "dock": "Dock 12",
        "gate": "Gate C",
        "appointment": "8:00 AM",
        "production_line": "Line 4 — Model Y battery pack assembly",
        "hourly_downtime_cost": 1_800_000,
        "lane_on_time_rate": 0.74,
        "weather_risk": "winter storm developing on I-80 near Donner Pass in ~6 hours",
        "hos_hours_remaining": 4.0,
        "requires_sealed": True,
        "requires_temp_control": True,
        "temp_range": "15–25°C",
    },
    "JD-BEARING-0788": {
        "shipper": "John Deere Waterloo Works",
        "carrier": "Heartland Carriers",
        "driver_name": "Dave",
        "commodity": "precision axle bearings",
        "origin": "Rockford, Illinois",
        "lane": "Rockford, IL → Waterloo, IA (US-20)",
        "dock": "Dock 3",
        "gate": "Gate A",
        "appointment": "10:30 AM",
        "production_line": "Line 2 — tractor final assembly",
        "hourly_downtime_cost": 420_000,
        "lane_on_time_rate": 0.91,
        "weather_risk": None,
        "hos_hours_remaining": 8.5,
        "requires_sealed": False,
        "requires_temp_control": False,
        "temp_range": None,
    },
    "BOEING-FAST-1102": {
        "shipper": "Boeing Everett Factory",
        "carrier": "Cascade Logistics",
        "driver_name": "Priya",
        "commodity": "titanium fasteners (AOG)",
        "origin": "Portland, Oregon",
        "lane": "Portland, OR → Everett, WA (I-5)",
        "dock": "Dock 7",
        "gate": "Gate B",
        "appointment": "2:00 PM",
        "production_line": "777X wing assembly",
        "hourly_downtime_cost": 950_000,
        "lane_on_time_rate": 0.83,
        "weather_risk": "heavy congestion reported on I-5 through Seattle",
        "hos_hours_remaining": 6.0,
        "requires_sealed": True,
        "requires_temp_control": False,
        "temp_range": None,
    },
}

# ---------------------------------------------------------------------------
# Scenario 3 — Multilingual supplier compliance calls
# ---------------------------------------------------------------------------
#
# When tariffs / routing / terms change, FreightVoice calls the supplier
# network to confirm new pricing, lead times, and compliance docs — speaking
# the supplier's language and logging every response as structured data.
SUPPLIERS = {
    "APPL-CAM-221": {
        "buyer": "Apple",
        "supplier": "Shenzhen Optics Co.",
        "contact_name": "Ms. Chen",
        "language": "Mandarin",
        "component": "camera module assemblies",
        "current_unit_price_usd": 14.20,
        "current_lead_time_days": 21,
        "change_event": "new 25% Section 301 tariff effective the 1st of next month",
        "docs_needed": [
            "updated commercial invoice",
            "country-of-origin certificate",
        ],
    },
    "APPL-PCB-118": {
        "buyer": "Apple",
        "supplier": "Guadalajara Circuitos S.A.",
        "contact_name": "Sr. Ramírez",
        "language": "Spanish",
        "component": "flexible PCB substrates",
        "current_unit_price_usd": 8.75,
        "current_lead_time_days": 14,
        "change_event": "USMCA routing change shifting transit from air to ground",
        "docs_needed": [
            "USMCA certificate of origin",
            "updated lead-time confirmation",
        ],
    },
}


def score_risk(shipment: dict, driver_confident: bool, eta_minutes_late: int = 0) -> dict:
    """Score the risk that this inbound shipment disrupts the production line.

    Combines the same signals a human dispatcher would weigh: the carrier's
    historical on-time rate on this lane, developing weather on the route, the
    driver's remaining Hours-of-Service, how the driver sounded on the call,
    and any reported lateness vs. the dock appointment.

    Returns a dict with a 0–100 ``score``, a ``level`` (low/medium/high), the
    contributing ``factors``, and a concrete ``recommended_action`` for the
    logistics team — sized to the production line's hourly downtime cost.
    """
    score = 0
    factors: list[str] = []

    otr = shipment.get("lane_on_time_rate", 1.0)
    if otr < 0.85:
        pts = round((0.85 - otr) * 200)  # 74% -> 22 pts
        score += pts
        factors.append(f"Carrier on-time rate is only {int(otr * 100)}% on this lane")

    if shipment.get("weather_risk"):
        score += 30
        factors.append(shipment["weather_risk"])

    hos = shipment.get("hos_hours_remaining")
    if hos is not None and hos < 6:
        score += 25
        factors.append(f"Driver's HOS clock has only {hos} hours remaining")

    if not driver_confident:
        score += 20
        factors.append("Driver sounded uncertain about timing on the check call")

    if eta_minutes_late > 0:
        score += min(eta_minutes_late // 10, 25)
        factors.append(f"Reported ETA is ~{eta_minutes_late} min behind the dock appointment")

    score = min(score, 100)
    level = "low" if score < 30 else "medium" if score < 60 else "high"

    cost = shipment.get("hourly_downtime_cost", 0)
    cost_str = f"${cost / 1_000_000:.1f}M/hour" if cost >= 1_000_000 else f"${cost / 1_000:.0f}K/hour"
    line = shipment.get("production_line", "the production line")

    if level == "high":
        recommended_action = (
            f"ALERT logistics now: high risk to {line} (downtime costs {cost_str}). "
            "Recommend sourcing an alternate carrier and pre-staging emergency stock, "
            "or adjusting the production schedule before the part is needed."
        )
    elif level == "medium":
        recommended_action = (
            f"Flag {line} for monitoring (downtime costs {cost_str}). "
            "Recommend confirming a backup carrier is on standby and re-checking ETA in 2 hours."
        )
    else:
        recommended_action = (
            f"No action needed. Shipment is on track for {line}; "
            "log the confirmation and continue normal monitoring."
        )

    return {
        "score": score,
        "level": level,
        "factors": factors,
        "hourly_downtime_cost": cost,
        "recommended_action": recommended_action,
    }
