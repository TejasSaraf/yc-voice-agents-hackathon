#
# Copyright (c) 2024–2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Synthetic backend data for the FreightVoice shipper-side voice agent.

FreightVoice is the inbound-coordination layer for manufacturers (Tesla, John
Deere, Boeing, Apple ...). It calls carriers and suppliers on the shipper's
behalf instead of the logistics team making 80 manual calls a day.

ALL DATA HERE IS SYNTHETIC — hand-authored to look like a real TMS/ERP export
for a single morning's inbound shift. Company/factory names are real public
facts; every operational detail (load IDs, carriers, drivers, prices, on-time
rates, weather) is fabricated for the demo. To go live, swap these dicts for
calls to a real TMS / WMS / ERP from inside the tool functions in
``freight_scenarios.py`` — the agent logic doesn't change.

Two scenarios are modeled:

  * SHIPMENTS  — inbound carrier check-in calls (Problems 1 & 2):
                 confirm ETA + dock, verify cargo condition, score delivery
                 risk, and protect the production line.
  * SUPPLIERS  — multilingual supplier compliance calls (Problem 3):
                 confirm pricing under new tariffs, lead times, and docs.

Keys are matched case-insensitively in the bot (load IDs / supplier IDs are
upper-cased before lookup).

Schema note: ``score_risk`` and ``freight_scenarios.py`` depend on these keys,
so keep them on every record — shipper, carrier, driver_name, commodity,
origin, lane, dock, gate, appointment, production_line, hourly_downtime_cost,
lane_on_time_rate, weather_risk, hos_hours_remaining, requires_sealed,
requires_temp_control, temp_range. The remaining fields (carrier_mc,
driver_phone, po_number, units, weight_lbs, scheduled_date,
prior_loads_on_lane) are enrichment — they make the data feel like a real feed
and are available to future tools/dashboards.
"""

# ---------------------------------------------------------------------------
# Scenario 1 & 2 — Inbound carrier check-in / production-line protection
# ---------------------------------------------------------------------------
#
# A morning's inbound shift across eight plants. The mix is deliberate: a few
# routine low-risk arrivals, several worth monitoring, and a couple of genuine
# exceptions (TSLA-BAT-0412, GM-CHIP-5567) — exactly the 5-exceptions-out-of-80
# story FreightVoice is built around.
#
#   hourly_downtime_cost : USD lost per hour if this line stops for lack of part
#   lane_on_time_rate    : historical on-time % for this carrier on this lane
#   weather_risk         : developing weather/traffic event on route (or None)
#   hos_hours_remaining  : driver Hours-of-Service clock remaining
#   requires_sealed      : load must arrive with seal intact
#   requires_temp_control: load is temperature-controlled
SHIPMENTS = {
    # --- Genuine exceptions (high risk) -----------------------------------
    "TSLA-BAT-0412": {
        "shipper": "Tesla Austin Gigafactory",
        "carrier": "Sierra Freight Lines",
        "carrier_mc": "MC-118402",
        "driver_name": "Miguel",
        "driver_phone": "+1-775-555-0142",
        "commodity": "lithium-ion battery cells",
        "po_number": "PO-TSLA-99231",
        "units": "18 pallets",
        "weight_lbs": 41200,
        "origin": "Reno, Nevada",
        "lane": "Reno, NV → Austin, TX (I-80 / I-35)",
        "dock": "Dock 12",
        "gate": "Gate C",
        "appointment": "8:00 AM",
        "scheduled_date": "today",
        "production_line": "Line 4 — Model Y battery pack assembly",
        "hourly_downtime_cost": 1_800_000,
        "lane_on_time_rate": 0.74,
        "prior_loads_on_lane": 212,
        "weather_risk": "winter storm developing on I-80 near Donner Pass in ~6 hours",
        "hos_hours_remaining": 4.0,
        "requires_sealed": True,
        "requires_temp_control": True,
        "temp_range": "15–25°C",
    },
    "GM-CHIP-5567": {
        "shipper": "GM Factory ZERO, Detroit",
        "carrier": "Great Lakes Drayage",
        "carrier_mc": "MC-204417",
        "driver_name": "Terrence",
        "driver_phone": "+1-310-555-0188",
        "commodity": "automotive semiconductor modules",
        "po_number": "PO-GM-44120",
        "units": "6 pallets",
        "weight_lbs": 9800,
        "origin": "Port of Los Angeles (import from Taiwan)",
        "lane": "Port of LA, CA → Detroit, MI (I-10 / I-44 / I-70)",
        "dock": "Dock 7",
        "gate": "Gate B",
        "appointment": "9:00 AM",
        "scheduled_date": "today",
        "production_line": "Line 1 — EV controller assembly",
        "hourly_downtime_cost": 1_350_000,
        "lane_on_time_rate": 0.81,
        "prior_loads_on_lane": 64,
        "weather_risk": "customs hold flagged at port; container not yet released",
        "hos_hours_remaining": 5.0,
        "requires_sealed": True,
        "requires_temp_control": False,
        "temp_range": None,
    },
    # --- Worth monitoring (medium risk) -----------------------------------
    "FORD-SEAT-2231": {
        "shipper": "Ford Dearborn Truck Plant",
        "carrier": "Frontera Logistics",
        "carrier_mc": "MC-330911",
        "driver_name": "Rosa",
        "driver_phone": "+52-81-5555-0177",
        "commodity": "seat assemblies",
        "po_number": "PO-FORD-72213",
        "units": "22 pallets",
        "weight_lbs": 14300,
        "origin": "Monterrey, Mexico",
        "lane": "Monterrey, MX → Dearborn, MI (I-35 / I-69)",
        "dock": "Dock 4",
        "gate": "Gate A",
        "appointment": "11:00 AM",
        "scheduled_date": "today",
        "production_line": "Line 6 — F-150 final assembly",
        "hourly_downtime_cost": 720_000,
        "lane_on_time_rate": 0.79,
        "prior_loads_on_lane": 138,
        "weather_risk": None,
        "hos_hours_remaining": 5.0,
        "requires_sealed": True,
        "requires_temp_control": False,
        "temp_range": None,
    },
    "BOEING-FAST-1102": {
        "shipper": "Boeing Everett Factory",
        "carrier": "Cascade Logistics",
        "carrier_mc": "MC-551203",
        "driver_name": "Priya",
        "driver_phone": "+1-503-555-0166",
        "commodity": "titanium fasteners (AOG)",
        "po_number": "PO-BA-10027",
        "units": "3 crates",
        "weight_lbs": 2600,
        "origin": "Portland, Oregon",
        "lane": "Portland, OR → Everett, WA (I-5)",
        "dock": "Dock 9",
        "gate": "Gate B",
        "appointment": "2:00 PM",
        "scheduled_date": "today",
        "production_line": "777X wing assembly",
        "hourly_downtime_cost": 950_000,
        "lane_on_time_rate": 0.83,
        "prior_loads_on_lane": 47,
        "weather_risk": "heavy congestion reported on I-5 through Seattle",
        "hos_hours_remaining": 6.0,
        "requires_sealed": True,
        "requires_temp_control": False,
        "temp_range": None,
    },
    "BOEING-COMP-1180": {
        "shipper": "Boeing Renton Factory",
        "carrier": "Cascade Logistics",
        "carrier_mc": "MC-551203",
        "driver_name": "Hank",
        "driver_phone": "+1-206-555-0153",
        "commodity": "composite wing panels",
        "po_number": "PO-BA-10044",
        "units": "2 flatbed loads",
        "weight_lbs": 18800,
        "origin": "Spokane, Washington",
        "lane": "Spokane, WA → Renton, WA (I-90)",
        "dock": "Dock 2",
        "gate": "Gate A",
        "appointment": "1:30 PM",
        "scheduled_date": "today",
        "production_line": "737 MAX wing line",
        "hourly_downtime_cost": 880_000,
        "lane_on_time_rate": 0.80,
        "prior_loads_on_lane": 73,
        "weather_risk": "snow advisory on Snoqualmie Pass in ~4 hours",
        "hos_hours_remaining": 7.0,
        "requires_sealed": False,
        "requires_temp_control": False,
        "temp_range": None,
    },
    "TSLA-SEAT-0420": {
        "shipper": "Tesla Austin Gigafactory",
        "carrier": "Lone Star Transport",
        "carrier_mc": "MC-409882",
        "driver_name": "Diego",
        "driver_phone": "+52-81-5555-0191",
        "commodity": "seat assemblies",
        "po_number": "PO-TSLA-99244",
        "units": "16 pallets",
        "weight_lbs": 11200,
        "origin": "Monterrey, Mexico",
        "lane": "Monterrey, MX → Austin, TX (I-35)",
        "dock": "Dock 14",
        "gate": "Gate C",
        "appointment": "10:30 AM",
        "scheduled_date": "today",
        "production_line": "Line 4 — Model Y interior",
        "hourly_downtime_cost": 640_000,
        "lane_on_time_rate": 0.82,
        "prior_loads_on_lane": 159,
        "weather_risk": None,
        "hos_hours_remaining": 5.5,
        "requires_sealed": True,
        "requires_temp_control": False,
        "temp_range": None,
    },
    "CAT-ENGINE-7742": {
        "shipper": "Caterpillar East Peoria",
        "carrier": "Prairie Freight Co.",
        "carrier_mc": "MC-277510",
        "driver_name": "Bill",
        "driver_phone": "+1-309-555-0124",
        "commodity": "diesel engine blocks",
        "po_number": "PO-CAT-58811",
        "units": "8 crates",
        "weight_lbs": 32400,
        "origin": "Indianapolis, Indiana",
        "lane": "Indianapolis, IN → East Peoria, IL (I-74)",
        "dock": "Dock 5",
        "gate": "Gate A",
        "appointment": "12:00 PM",
        "scheduled_date": "today",
        "production_line": "Line 3 — large dozer assembly",
        "hourly_downtime_cost": 510_000,
        "lane_on_time_rate": 0.84,
        "prior_loads_on_lane": 91,
        "weather_risk": "thunderstorms forecast along I-74 this afternoon",
        "hos_hours_remaining": 4.5,
        "requires_sealed": False,
        "requires_temp_control": False,
        "temp_range": None,
    },
    # --- Routine on-track arrivals (low risk) -----------------------------
    "JD-BEARING-0788": {
        "shipper": "John Deere Waterloo Works",
        "carrier": "Heartland Carriers",
        "carrier_mc": "MC-160044",
        "driver_name": "Dave",
        "driver_phone": "+1-815-555-0119",
        "commodity": "precision axle bearings",
        "po_number": "PO-JD-30188",
        "units": "10 pallets",
        "weight_lbs": 7600,
        "origin": "Rockford, Illinois",
        "lane": "Rockford, IL → Waterloo, IA (US-20)",
        "dock": "Dock 3",
        "gate": "Gate A",
        "appointment": "10:30 AM",
        "scheduled_date": "today",
        "production_line": "Line 2 — tractor final assembly",
        "hourly_downtime_cost": 420_000,
        "lane_on_time_rate": 0.91,
        "prior_loads_on_lane": 304,
        "weather_risk": None,
        "hos_hours_remaining": 8.5,
        "requires_sealed": False,
        "requires_temp_control": False,
        "temp_range": None,
    },
    "JD-HYDRAULIC-0631": {
        "shipper": "John Deere Dubuque Works",
        "carrier": "Heartland Carriers",
        "carrier_mc": "MC-160044",
        "driver_name": "Carla",
        "driver_phone": "+1-563-555-0137",
        "commodity": "hydraulic pump units",
        "po_number": "PO-JD-30205",
        "units": "12 pallets",
        "weight_lbs": 9100,
        "origin": "Cedar Rapids, Iowa",
        "lane": "Cedar Rapids, IA → Dubuque, IA (US-151)",
        "dock": "Dock 1",
        "gate": "Gate A",
        "appointment": "9:30 AM",
        "scheduled_date": "today",
        "production_line": "Line 5 — backhoe assembly",
        "hourly_downtime_cost": 380_000,
        "lane_on_time_rate": 0.93,
        "prior_loads_on_lane": 188,
        "weather_risk": None,
        "hos_hours_remaining": 9.0,
        "requires_sealed": False,
        "requires_temp_control": False,
        "temp_range": None,
    },
    "INTEL-WAFER-9001": {
        "shipper": "Intel Ocotillo, Chandler AZ",
        "carrier": "Desert Star Logistics",
        "carrier_mc": "MC-612009",
        "driver_name": "Sam",
        "driver_phone": "+1-480-555-0172",
        "commodity": "silicon wafers (Class 100 cleanroom)",
        "po_number": "PO-INTC-77410",
        "units": "4 sealed totes",
        "weight_lbs": 3200,
        "origin": "Phoenix, Arizona",
        "lane": "Phoenix, AZ → Chandler, AZ (Loop 202)",
        "dock": "Dock 8",
        "gate": "Gate D",
        "appointment": "7:30 AM",
        "scheduled_date": "today",
        "production_line": "Fab 42 — lithography intake",
        "hourly_downtime_cost": 2_100_000,
        "lane_on_time_rate": 0.94,
        "prior_loads_on_lane": 421,
        "weather_risk": None,
        "hos_hours_remaining": 9.5,
        "requires_sealed": True,
        "requires_temp_control": True,
        "temp_range": "20–22°C",
    },
    "RIVIAN-MOTOR-3300": {
        "shipper": "Rivian Normal Plant",
        "carrier": "Midwest Express Freight",
        "carrier_mc": "MC-488221",
        "driver_name": "Janet",
        "driver_phone": "+1-309-555-0148",
        "commodity": "electric drive units",
        "po_number": "PO-RIVN-21190",
        "units": "14 pallets",
        "weight_lbs": 16400,
        "origin": "Columbus, Ohio",
        "lane": "Columbus, OH → Normal, IL (I-70 / I-74)",
        "dock": "Dock 6",
        "gate": "Gate B",
        "appointment": "1:00 PM",
        "scheduled_date": "today",
        "production_line": "R1T drive-unit install",
        "hourly_downtime_cost": 560_000,
        "lane_on_time_rate": 0.88,
        "prior_loads_on_lane": 52,
        "weather_risk": None,
        "hos_hours_remaining": 8.0,
        "requires_sealed": False,
        "requires_temp_control": False,
        "temp_range": None,
    },
    "TSLA-BAT-0455": {
        "shipper": "Tesla Fremont Factory",
        "carrier": "Bay Area Carriers",
        "carrier_mc": "MC-501776",
        "driver_name": "Wei",
        "driver_phone": "+1-510-555-0199",
        "commodity": "lithium-ion battery cells",
        "po_number": "PO-TSLA-99260",
        "units": "20 pallets",
        "weight_lbs": 44800,
        "origin": "Sparks, Nevada",
        "lane": "Sparks, NV → Fremont, CA (I-80)",
        "dock": "Dock 11",
        "gate": "Gate C",
        "appointment": "3:00 PM",
        "scheduled_date": "today",
        "production_line": "Model 3 battery pack assembly",
        "hourly_downtime_cost": 1_650_000,
        "lane_on_time_rate": 0.90,
        "prior_loads_on_lane": 276,
        "weather_risk": None,
        "hos_hours_remaining": 9.0,
        "requires_sealed": True,
        "requires_temp_control": True,
        "temp_range": "15–25°C",
    },
}

# ---------------------------------------------------------------------------
# Scenario 3 — Multilingual supplier compliance calls
# ---------------------------------------------------------------------------
#
# When tariffs / routing / terms change, FreightVoice calls the supplier
# network to confirm new pricing, lead times, and compliance docs — speaking
# the supplier's language and logging every response as structured data.
#
#   Schema (used by freight_scenarios.py): buyer, supplier, contact_name,
#   language, component, current_unit_price_usd, current_lead_time_days,
#   change_event, docs_needed. Enrichment: supplier_country, contact_phone,
#   annual_volume_units, current_incoterms.
SUPPLIERS = {
    "APPL-CAM-221": {
        "buyer": "Apple",
        "supplier": "Shenzhen Optics Co.",
        "supplier_country": "China",
        "contact_name": "Ms. Chen",
        "contact_phone": "+86-755-5555-0123",
        "language": "Mandarin",
        "component": "camera module assemblies",
        "current_unit_price_usd": 14.20,
        "current_lead_time_days": 21,
        "current_incoterms": "FOB Shenzhen",
        "annual_volume_units": 4_800_000,
        "change_event": "new 25% Section 301 tariff effective the 1st of next month",
        "docs_needed": [
            "updated commercial invoice",
            "country-of-origin certificate",
        ],
    },
    "APPL-PCB-118": {
        "buyer": "Apple",
        "supplier": "Guadalajara Circuitos S.A.",
        "supplier_country": "Mexico",
        "contact_name": "Sr. Ramírez",
        "contact_phone": "+52-33-5555-0144",
        "language": "Spanish",
        "component": "flexible PCB substrates",
        "current_unit_price_usd": 8.75,
        "current_lead_time_days": 14,
        "current_incoterms": "DAP Guadalajara",
        "annual_volume_units": 2_100_000,
        "change_event": "USMCA routing change shifting transit from air to ground",
        "docs_needed": [
            "USMCA certificate of origin",
            "updated lead-time confirmation",
        ],
    },
    "APPL-ENCL-305": {
        "buyer": "Apple",
        "supplier": "Hanoi Precision Enclosures JSC",
        "supplier_country": "Vietnam",
        "contact_name": "Mr. Pham",
        "contact_phone": "+84-24-5555-0188",
        "language": "Vietnamese",
        "component": "aluminum device enclosures",
        "current_unit_price_usd": 22.40,
        "current_lead_time_days": 28,
        "current_incoterms": "FOB Haiphong",
        "annual_volume_units": 3_300_000,
        "change_event": "supplier diversification — moving 30% of volume from China to Vietnam",
        "docs_needed": [
            "updated capacity commitment",
            "country-of-origin certificate",
            "quality conformance report",
        ],
    },
    "GM-HARN-410": {
        "buyer": "GM",
        "supplier": "Shanghai Wiring Systems Ltd.",
        "supplier_country": "China",
        "contact_name": "Mr. Liu",
        "contact_phone": "+86-21-5555-0177",
        "language": "Mandarin",
        "component": "EV wiring harnesses",
        "current_unit_price_usd": 63.50,
        "current_lead_time_days": 35,
        "current_incoterms": "FOB Shanghai",
        "annual_volume_units": 900_000,
        "change_event": "new tariff schedule plus a request to dual-source through a Mexico DC",
        "docs_needed": [
            "revised price schedule",
            "country-of-origin certificate",
        ],
    },
    "FORD-SENS-512": {
        "buyer": "Ford",
        "supplier": "Stuttgart Sensorik GmbH",
        "supplier_country": "Germany",
        "contact_name": "Herr Brandt",
        "contact_phone": "+49-711-5555-0166",
        "language": "German",
        "component": "ADAS radar sensors",
        "current_unit_price_usd": 41.90,
        "current_lead_time_days": 30,
        "current_incoterms": "CIF Bremerhaven",
        "annual_volume_units": 1_400_000,
        "change_event": "EU export-control reclassification requiring new compliance paperwork",
        "docs_needed": [
            "updated export-control declaration",
            "CE conformance documentation",
        ],
    },
    "BA-PANEL-628": {
        "buyer": "Boeing",
        "supplier": "Sheffield Composites Ltd.",
        "supplier_country": "United Kingdom",
        "contact_name": "Ms. Whitcombe",
        "contact_phone": "+44-114-555-0133",
        "language": "English",
        "component": "carbon-fiber fuselage panels",
        "current_unit_price_usd": 1850.00,
        "current_lead_time_days": 45,
        "current_incoterms": "DAP Everett",
        "annual_volume_units": 12_000,
        "change_event": "post-Brexit customs change altering documentation and duty terms",
        "docs_needed": [
            "updated UK origin declaration",
            "AS9100 conformance certificate",
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


def fleet_overview(driver_confident: bool = True, eta_minutes_late: int = 0) -> dict:
    """Summarize the whole inbound fleet the way a logistics dashboard would.

    Scores every shipment at its baseline (pre-call) state and buckets them by
    risk level, so the demo can open with "12 inbound today, 2 flagged" before
    drilling into a single call. ``driver_confident`` / ``eta_minutes_late``
    let you model a worst-case sweep if desired.

    Returns counts per level, the flagged load IDs, and the total hourly
    downtime exposure sitting behind the medium/high shipments.
    """
    buckets: dict = {"low": [], "medium": [], "high": []}
    exposure = 0
    for load_id, shipment in SHIPMENTS.items():
        risk = score_risk(shipment, driver_confident, eta_minutes_late)
        buckets[risk["level"]].append(load_id)
        if risk["level"] in ("medium", "high"):
            exposure += shipment.get("hourly_downtime_cost", 0)

    flagged = buckets["high"] + buckets["medium"]
    return {
        "total_inbound": len(SHIPMENTS),
        "counts": {level: len(ids) for level, ids in buckets.items()},
        "flagged_load_ids": flagged,
        "hourly_downtime_exposure_usd": exposure,
        "summary": (
            f"{len(SHIPMENTS)} inbound shipments today: "
            f"{len(buckets['high'])} high-risk, {len(buckets['medium'])} medium, "
            f"{len(buckets['low'])} on track. "
            f"${exposure / 1_000_000:.1f}M/hour of production exposure behind the flagged loads."
        ),
    }
