"""FreightVoice scenario builders — shared by the Nemotron and GPT bots.

Each builder returns ``(tool_functions, system_instruction, greeting)`` so the
two bot entrypoints (``bot-freightvoice.py`` for the Nemotron pipeline,
``bot-freightvoice-gpt.py`` for the GPT/Gradium fallback) stay in sync — only
the STT/LLM services differ between them.

Scenarios (selected via FREIGHTVOICE_SCENARIO):
  * carrier     — Problems 1 & 2: inbound carrier check-in + line protection
  * compliance  — Problem 3: multilingual supplier compliance
"""

import asyncio
import dataclasses
import os
from datetime import datetime
from enum import Enum

import aiohttp
from loguru import logger
from pipecat.frames.frames import EndTaskFrame, FunctionCallResultProperties
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from freight_backend import SHIPMENTS, SUPPLIERS
from risk_scorer import RiskLevel, compute_risk_score, fetch_weather_risk

# ---------------------------------------------------------------------------
# Dashboard live-update helper
# ---------------------------------------------------------------------------

_DASHBOARD_API_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:8000").rstrip("/")

# Most-recent carrier call_state, set when a scenario is built. The bot reads
# this in its post-call finalize hook to enrich the call record.
_LAST_CALL_STATE: dict | None = None

# Deterministic spoken opening line for the most recent carrier scenario, used
# by the bot to greet instantly via TTS (skipping the first LLM round-trip).
_LAST_OPENING_LINE: str | None = None


def _jsonable(value):
    """Recursively convert dataclasses (RiskResult, SignalBreakdown) and enums
    (RiskLevel) into plain JSON-serializable types. The risk result is stored as
    a live dataclass in call_state, so it must be flattened before the call
    record is persisted or shipped to Cekura (otherwise json.dumps raises
    'Object of type RiskResult is not JSON serializable')."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def get_last_call_state() -> dict:
    """Return a JSON-safe copy of the most recent call's scenario state.

    The raw ``risk_result`` is a ``RiskResult`` dataclass; we flatten it (and
    add the derived ``must_alert`` flag the eval/self-improve tooling reads) so
    the whole state can be persisted and observed without serialization errors.
    """
    if not _LAST_CALL_STATE:
        return {}
    state = _jsonable(dict(_LAST_CALL_STATE))
    risk = state.get("risk_result")
    if isinstance(risk, dict) and "level" in risk:
        risk["must_alert"] = risk.get("level") in ("WARNING", "CRITICAL")
    return state


def get_opening_line() -> str | None:
    """Return the deterministic spoken opening for the most recent scenario."""
    return _LAST_OPENING_LINE


async def _push_call_update(load_id: str, update: dict) -> None:
    """Fire-and-forget POST of the current call state to the dashboard.

    Hard-capped at 1.5s so a slow API server never stalls the voice pipeline.
    Failures are logged at DEBUG only — the bot keeps talking even if the
    dashboard is offline.
    """
    payload = {"load_id": load_id, "ts": datetime.now().isoformat(), **update}
    url = f"{_DASHBOARD_API_URL}/api/calls/update"
    try:
        timeout = aiohttp.ClientTimeout(total=1.5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.warning(
                        f"Dashboard update {resp.status} for {load_id}: {body[:200]}"
                    )
    except Exception as exc:
        logger.debug(f"Dashboard update suppressed for {load_id}: {exc}")


def _fire_update(load_id: str, update: dict) -> None:
    """Schedule _push_call_update without awaiting — never blocks the LLM."""
    asyncio.create_task(_push_call_update(load_id, update))


def _appointment_minutes_from_now(appointment: str) -> int | None:
    """Parse an appointment string like '8:00 AM' into minutes from now."""
    for fmt in ("%I:%M %p", "%I %p"):
        try:
            appt = datetime.strptime(appointment, fmt)
            now = datetime.now()
            appt = appt.replace(year=now.year, month=now.month, day=now.day)
            return int((appt - now).total_seconds() / 60)
        except ValueError:
            continue
    logger.warning(f"Could not parse appointment time '{appointment}'")
    return None


def build_carrier_checkin(load_id: str) -> tuple[list, str, str]:
    """Problems 1 & 2: inbound carrier check-in + production-line risk.

    FreightVoice is the OUTBOUND caller, calling a driver on the shipper's
    behalf to confirm ETA + dock, verify cargo condition, score delivery risk,
    and alert the logistics team only when the line is at risk.
    """
    shipment = SHIPMENTS[load_id]

    call_state: dict = {
        "current_location": None,
        "eta": None,
        "driver_sentiment": "calm",
        "eta_minutes_from_now": None,
        "cargo_ok": None,
        "dock_notified": False,
        "risk_result": None,
        "logistics_alerted": False,
    }
    # Expose this call's mutable state so the bot can attach it to the post-call
    # record (for Cekura metadata + local self-improve analysis).
    global _LAST_CALL_STATE
    _LAST_CALL_STATE = call_state

    async def confirm_eta(
        params: FunctionCallParams,
        current_location: str,
        eta: str,
        driver_sentiment: str = "calm",
        eta_minutes_from_now: int | None = None,
    ) -> None:
        """Record the driver's current location, ETA, and tone. Call this as
        soon as the driver tells you where they are and when they expect to
        arrive.

        Args:
            current_location: Where the driver says they are now, in their
                words (e.g. "in Reno", "about 20 out on the 94").
            eta: The arrival time the driver gives, in their words
                (e.g. "7:30", "about 20 minutes out").
            driver_sentiment: Your honest read of the driver's tone.
                Must be exactly one of: "confident", "calm", "uncertain",
                "frustrated". This is the highest-weighted signal in the risk
                model — be precise.
                  "confident"  → clear, specific, no hedging
                  "calm"       → relaxed, on track, no concerns raised
                  "uncertain"  → hedging, vague timing, mentions problems
                  "frustrated" → stressed, complaining, evasive about timing
            eta_minutes_from_now: Your best estimate of how many minutes until
                the driver arrives, based on what they said. Convert verbal
                cues — "about 20 out" → 20, "7:30" and it's 6:45 → 45.
                Leave None if the driver gave genuinely no usable number.
        """
        call_state["current_location"] = current_location
        call_state["eta"] = eta
        call_state["driver_sentiment"] = driver_sentiment
        call_state["eta_minutes_from_now"] = eta_minutes_from_now

        _fire_update(load_id, {
            "stage": "eta_confirmed",
            "current_location": current_location,
            "eta_text": eta,
            "eta_minutes_from_now": eta_minutes_from_now,
            "driver_sentiment": driver_sentiment,
        })

        await params.result_callback(
            {
                "ok": True,
                "load_id": load_id,
                "commodity": shipment["commodity"],
                "scheduled_appointment": shipment["appointment"],
                "recorded_eta": eta,
                "recorded_sentiment": driver_sentiment,
                "next": "Verify cargo condition, then assign the dock and assess risk.",
            }
        )

    async def verify_cargo_condition(
        params: FunctionCallParams,
        is_sealed: bool,
        temp_verified: bool = False,
        seal_number: str | None = None,
    ) -> None:
        """Verify the cargo meets this shipper's receiving requirements. Only
        ask about temperature if this shipment is temperature-controlled.

        Args:
            is_sealed: Whether the driver confirms the load seal is intact.
            temp_verified: Whether the driver confirms temperature is in range
                (only relevant for temperature-controlled loads).
            seal_number: The seal number if the driver reads it out. Optional.
        """
        problems = []
        if shipment["requires_sealed"] and not is_sealed:
            problems.append("seal NOT confirmed intact")
        if shipment["requires_temp_control"] and not temp_verified:
            problems.append(f"temperature NOT verified (requires {shipment['temp_range']})")
        call_state["cargo_ok"] = not problems

        _fire_update(load_id, {
            "stage": "cargo_verified",
            "cargo_ok": not problems,
            "cargo_problems": problems or None,
            "seal_number": seal_number,
        })

        await params.result_callback(
            {
                "ok": not problems,
                "requires_sealed": shipment["requires_sealed"],
                "requires_temp_control": shipment["requires_temp_control"],
                "seal_number": seal_number,
                "problems": problems or None,
            }
        )

    async def assign_dock(params: FunctionCallParams) -> None:
        """Notify the dock team to prep the bay and tell the driver where to
        check in. Call this once ETA is confirmed so receiving is ready before
        the truck arrives (proactive dock coordination)."""
        call_state["dock_notified"] = True
        _fire_update(load_id, {
            "stage": "dock_assigned",
            "dock_notified": True,
            "dock": shipment["dock"],
            "gate": shipment["gate"],
        })
        await params.result_callback(
            {
                "ok": True,
                "dock": shipment["dock"],
                "gate": shipment["gate"],
                "appointment": shipment["appointment"],
                "instruction": (
                    f"Dock team notified to have {shipment['dock']} ready. "
                    f"Tell the driver to check in at {shipment['gate']}."
                ),
            }
        )

    async def assess_risk(params: FunctionCallParams) -> None:
        """Score the risk this shipment poses to the production line using the
        FreightVoice predictive model (voice sentiment + historical OTD + time
        pressure + NOAA weather + ETA vagueness). Call this after confirming
        ETA. If the result is WARNING or CRITICAL, you MUST then call
        alert_logistics_team."""
        weather_risk = await fetch_weather_risk(shipment["lane"])
        deadline_minutes = _appointment_minutes_from_now(shipment["appointment"])

        result = compute_risk_score(
            sentiment=call_state["driver_sentiment"],
            historical_otd_rate=shipment["lane_on_time_rate"],
            eta_minutes_from_now=call_state["eta_minutes_from_now"],
            deadline_minutes_from_now=deadline_minutes,
            weather_risk=weather_risk,
            hourly_downtime_cost=shipment["hourly_downtime_cost"],
            production_line=shipment["production_line"],
            load_id=load_id,
        )
        call_state["risk_result"] = result

        signal_summary = {
            name: {
                "label": s.label,
                "contribution": s.contribution,
                "weight": s.weight,
            }
            for name, s in result.signals.items()
        }

        _fire_update(load_id, {
            "stage": "risk_assessed",
            "live_risk": {
                "score": result.score,
                "level": result.level.value,
                "raw":   result.raw_score,
                "signals": signal_summary,
                "recommended_action": result.recommended_action,
                "next_checkin_minutes": result.next_checkin_minutes,
            },
        })

        await params.result_callback(
            {
                "load_id": load_id,
                "production_line": shipment["production_line"],
                "risk_score": result.score,
                "risk_level": result.level.value,
                "raw_score": result.raw_score,
                "signals": signal_summary,
                "recommended_action": result.recommended_action,
                "next_checkin_minutes": result.next_checkin_minutes,
                "must_alert": result.level in (RiskLevel.WARNING, RiskLevel.CRITICAL),
            }
        )

    async def alert_logistics_team(
        params: FunctionCallParams,
        recommended_action: str,
    ) -> None:
        """Fire an alert to the shipper's logistics team. Call this ONLY when
        assess_risk returned WARNING or CRITICAL — the whole point is that the
        team handles exceptions, not every routine on-time arrival.

        Args:
            recommended_action: The concrete action you're recommending (source
                an alternate carrier, pre-stage stock, adjust the schedule, etc.).
        """
        call_state["logistics_alerted"] = True
        result = call_state.get("risk_result")
        score = result.score if result else "?"
        level = result.level.value if result else "?"

        _fire_update(load_id, {
            "stage": "alerted",
            "logistics_alerted": True,
            "alert_action": recommended_action,
        })

        logger.info(
            f"🚨 LOGISTICS ALERT {load_id} [{level}] score={score} "
            f"{shipment['production_line']} :: {recommended_action}"
        )
        await params.result_callback(
            {
                "ok": True,
                "alerted": shipment["shipper"],
                "production_line": shipment["production_line"],
                "risk_score": score,
                "risk_level": level,
                "recommended_action": recommended_action,
                "note": "Logistics team notified. You do NOT need to read the score or alert text to the driver.",
            }
        )

    async def end_call(params: FunctionCallParams) -> None:
        """End the call. Only call this AFTER you have said goodbye to the driver
        in the same turn. The pipeline flushes queued speech and then hangs up."""
        logger.info(f"end_call invoked for {load_id} — final state: {call_state}")
        # IMPORTANT: await this push (don't fire-and-forget). The very next line
        # tears down the pipeline via EndTaskFrame, which cancels any pending
        # asyncio tasks — so a fire-and-forget _fire_update here would be killed
        # before the POST lands, and the dashboard would never see the call
        # complete (live strip stuck "in progress", modal never closes).
        # _push_call_update is hard-capped at 1.5s and swallows errors.
        await _push_call_update(load_id, {
            "stage": "completed",
            "completed_at": datetime.now().isoformat(),
        })
        await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        await params.result_callback(
            {"ok": True}, properties=FunctionCallResultProperties(run_llm=False)
        )

    tool_functions = [
        confirm_eta,
        verify_cargo_condition,
        assign_dock,
        assess_risk,
        alert_logistics_team,
        end_call,
    ]

    cargo_line = "sealed" + (
        " and temperature-controlled" if shipment["requires_temp_control"] else ""
    )

    system_instruction = (
        f"You are FreightVoice, an inbound-logistics coordinator calling on behalf of "
        f"{shipment['shipper']}. You are making an OUTBOUND call to {shipment['driver_name']}, "
        f"the driver for {shipment['carrier']}, about load {load_id}: "
        f"{shipment['commodity']} from {shipment['origin']}, scheduled to deliver to "
        f"{shipment['dock']} at {shipment['appointment']}. This part feeds "
        f"{shipment['production_line']} — if it's late, the line is at risk.\n\n"
        "YOUR JOB on this call, in order:\n"
        "1. Confirm the driver's current location and ETA. Call confirm_eta with:\n"
        "   - driver_sentiment: your honest read of the driver's tone — exactly one of\n"
        "     \"confident\" (clear, specific, no hedging),\n"
        "     \"calm\" (relaxed, on track),\n"
        "     \"uncertain\" (hedging, vague, mentions problems),\n"
        "     \"frustrated\" (stressed, complaining, evasive).\n"
        "     This is the highest-weighted signal in the risk model. Be precise.\n"
        "   - eta_minutes_from_now: convert what the driver said to a minute count\n"
        "     (\"about 20 out\" → 20, \"seven thirty\" and it's 6:45 now → 45).\n"
        "     Use None only if they gave genuinely no usable number.\n"
        f"2. Verify the load is {cargo_line}. Call verify_cargo_condition.\n"
        "3. Proactively prep receiving: call assign_dock, then tell the driver the dock and "
        "which gate to check in at.\n"
        "4. Call assess_risk — it runs the predictive model and scores the risk to the "
        "production line. If it returns must_alert=true (WARNING or CRITICAL), call "
        "alert_logistics_team with the recommended action. Do NOT alarm the driver — "
        "the alert goes to the shipper's team, not to them.\n"
        "5. Give a short, warm sign-off confirming the team has been notified, then call "
        "end_call in the same turn.\n\n"
        "HOW TO TALK — you're a real dispatcher on the phone, not a chatbot:\n"
        "- Keep it to 1–2 short sentences per turn. Ask ONE thing at a time.\n"
        "- Lead the call; the driver is busy. Skip filler like \"Absolutely!\" or "
        "\"I'd be happy to.\" Go straight to the point.\n"
        "- Use contractions. Fragments are fine. Read times in words "
        "(\"seven thirty\", not \"7:30\").\n"
        "- Responses are spoken aloud. No bullet points, no emojis, no reading out tool names, "
        "JSON, or risk scores. Never read internal scores or alert text to the driver.\n\n"
        "Open the call by identifying yourself and the shipper, stating the scheduled "
        "delivery, and asking the driver to confirm their ETA and current location — "
        "like: \"Hi, this is FreightVoice calling on behalf of "
        f"{shipment['shipper']}. You're scheduled to deliver {shipment['commodity']} to "
        f"{shipment['dock']} at {shipment['appointment']}. Can you confirm your ETA and "
        "current location?\""
    )

    greeting = (
        "You are FreightVoice and you just dialed the driver. Open the call now: identify "
        f"yourself and {shipment['shipper']}, state the scheduled delivery of "
        f"{shipment['commodity']} to {shipment['dock']} at {shipment['appointment']}, and "
        "ask the driver to confirm their ETA and current location."
    )

    # Deterministic spoken opening — lets the bot greet INSTANTLY via TTS instead
    # of waiting ~2s for the LLM to generate the first turn (big perceived-latency
    # win right after the driver picks up). Matches the example in the prompt.
    global _LAST_OPENING_LINE
    _LAST_OPENING_LINE = (
        f"Hi, this is FreightVoice calling on behalf of {shipment['shipper']}. "
        f"You're scheduled to deliver {shipment['commodity']} to {shipment['dock']} "
        f"at {shipment['appointment']}. Can you confirm your ETA and current location?"
    )

    return tool_functions, system_instruction, greeting


def build_supplier_compliance(supplier_id: str) -> tuple[list, str, str]:
    """Problem 3: multilingual supplier compliance call.

    FreightVoice calls a supplier when tariffs / routing / terms change to
    confirm new pricing, lead times, and compliance docs — speaking the
    supplier's language — and logs every response as structured data,
    escalating only suppliers who cannot confirm compliance.
    """
    supplier = SUPPLIERS[supplier_id]

    call_state: dict = {
        "confirmed_unit_price_usd": None,
        "accepts_new_terms": None,
        "confirmed_lead_time_days": None,
        "docs_committed": None,
        "compliant": None,
        "escalated": False,
    }

    async def confirm_pricing(
        params: FunctionCallParams,
        confirmed_unit_price_usd: float,
        accepts_new_terms: bool,
    ) -> None:
        """Log the supplier's confirmed unit price under the changed conditions.

        Args:
            confirmed_unit_price_usd: The unit price the supplier confirms, in USD.
            accepts_new_terms: Whether the supplier accepts the new tariff/routing terms.
        """
        call_state["confirmed_unit_price_usd"] = confirmed_unit_price_usd
        call_state["accepts_new_terms"] = accepts_new_terms
        await params.result_callback(
            {
                "ok": True,
                "previous_unit_price_usd": supplier["current_unit_price_usd"],
                "confirmed_unit_price_usd": confirmed_unit_price_usd,
                "accepts_new_terms": accepts_new_terms,
            }
        )

    async def confirm_lead_time(
        params: FunctionCallParams,
        lead_time_days: int,
    ) -> None:
        """Log the supplier's updated lead time under the changed conditions.

        Args:
            lead_time_days: New lead time in days the supplier commits to.
        """
        call_state["confirmed_lead_time_days"] = lead_time_days
        await params.result_callback(
            {
                "ok": True,
                "previous_lead_time_days": supplier["current_lead_time_days"],
                "confirmed_lead_time_days": lead_time_days,
            }
        )

    async def request_compliance_docs(
        params: FunctionCallParams,
        docs_committed: bool,
    ) -> None:
        """Request the updated compliance documentation and log whether the
        supplier commits to providing it.

        Args:
            docs_committed: Whether the supplier commits to sending the required docs.
        """
        call_state["docs_committed"] = docs_committed
        await params.result_callback(
            {
                "ok": True,
                "docs_needed": supplier["docs_needed"],
                "docs_committed": docs_committed,
            }
        )

    async def log_compliance_result(
        params: FunctionCallParams,
        compliant: bool,
        summary: str,
    ) -> None:
        """Write the structured compliance record for this supplier. Call this
        once you've gathered pricing, lead time, and the docs commitment.

        Args:
            compliant: True if the supplier confirmed new pricing, lead time, AND
                committed to the required docs. False otherwise.
            summary: One-sentence summary of the supplier's response for the log.
        """
        call_state["compliant"] = compliant
        record = {
            "supplier_id": supplier_id,
            "supplier": supplier["supplier"],
            "buyer": supplier["buyer"],
            "component": supplier["component"],
            "language": supplier["language"],
            "change_event": supplier["change_event"],
            "confirmed_unit_price_usd": call_state["confirmed_unit_price_usd"],
            "accepts_new_terms": call_state["accepts_new_terms"],
            "confirmed_lead_time_days": call_state["confirmed_lead_time_days"],
            "docs_committed": call_state["docs_committed"],
            "compliant": compliant,
            "summary": summary,
        }
        logger.info(f"📋 COMPLIANCE RECORD {supplier_id}: {record}")
        await params.result_callback({"ok": True, "record": record})

    async def escalate_supplier(
        params: FunctionCallParams,
        reason: str,
    ) -> None:
        """Escalate this supplier to the human procurement team. Call this ONLY
        when the supplier cannot confirm compliance (won't accept terms, can't
        meet lead time, or won't commit to docs).

        Args:
            reason: Why this supplier is being escalated.
        """
        call_state["escalated"] = True
        logger.info(f"⚠️ ESCALATION {supplier_id} ({supplier['supplier']}): {reason}")
        await params.result_callback(
            {"ok": True, "escalated_to": f"{supplier['buyer']} procurement", "reason": reason}
        )

    async def end_call(params: FunctionCallParams) -> None:
        """End the call. Only call this AFTER you've said goodbye in the same
        turn (in the supplier's language). The pipeline flushes speech and hangs up."""
        logger.info(f"end_call invoked for {supplier_id} — final state: {call_state}")
        await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        await params.result_callback(
            {"ok": True}, properties=FunctionCallResultProperties(run_llm=False)
        )

    tool_functions = [
        confirm_pricing,
        confirm_lead_time,
        request_compliance_docs,
        log_compliance_result,
        escalate_supplier,
        end_call,
    ]

    docs_list = ", ".join(supplier["docs_needed"])

    system_instruction = (
        f"You are FreightVoice, a supply-chain compliance agent calling on behalf of "
        f"{supplier['buyer']}. You are making an OUTBOUND call to {supplier['contact_name']} "
        f"at {supplier['supplier']}, who supplies {supplier['component']}. A condition has "
        f"changed: {supplier['change_event']}. You need to re-confirm the commercial terms.\n\n"
        f"LANGUAGE: This supplier's working language is {supplier['language']}. Conduct the "
        f"call primarily in {supplier['language']}. You may code-switch to English for "
        "technical terms or if the contact switches. Be polite and professional.\n\n"
        "YOUR JOB on this call, in order:\n"
        "1. Confirm the unit price under the new conditions. Call confirm_pricing. "
        f"(Current price on file: ${supplier['current_unit_price_usd']:.2f} per unit.)\n"
        "2. Confirm the updated lead time. Call confirm_lead_time. "
        f"(Current lead time on file: {supplier['current_lead_time_days']} days.)\n"
        f"3. Request the required compliance documents ({docs_list}). Call "
        "request_compliance_docs.\n"
        "4. Call log_compliance_result with whether they're fully compliant and a summary.\n"
        "5. If they cannot confirm compliance, call escalate_supplier with the reason.\n"
        "6. Thank them and sign off in their language, then call end_call in the same turn.\n\n"
        "HOW TO TALK: Keep it to 1–2 short sentences per turn, one question at a time. "
        "Responses are spoken aloud — no bullet points, emojis, tool names, or JSON. "
        "Don't read internal records back to the supplier.\n\n"
        f"Open the call in {supplier['language']}: greet the contact, identify yourself and "
        f"{supplier['buyer']}, briefly state the change ({supplier['change_event']}), and ask "
        "to re-confirm pricing."
    )

    greeting = (
        f"You are FreightVoice and you just dialed {supplier['contact_name']} at "
        f"{supplier['supplier']}. Open the call now IN {supplier['language'].upper()}: greet "
        f"them, identify yourself and {supplier['buyer']}, briefly state the change "
        f"({supplier['change_event']}), and ask to re-confirm the unit price."
    )

    return tool_functions, system_instruction, greeting


def build_scenario(
    *,
    scenario: str | None = None,
    load_id: str | None = None,
    supplier_id: str | None = None,
) -> tuple[list, str, str]:
    """Select and build the active scenario.

    Per-call overrides take precedence over the environment defaults, falling
    back to env (then a hard default). This lets a dashboard-triggered call name
    its own load via the call's WebSocket body, while a bare ``uv run
    bot-freightvoice.py`` still works off ``.env``:

        FREIGHTVOICE_SCENARIO=carrier (default) | compliance
        FREIGHTVOICE_LOAD_ID / FREIGHTVOICE_SUPPLIER_ID pin the demo target.
    """
    scenario = (scenario or os.getenv("FREIGHTVOICE_SCENARIO", "carrier")).strip().lower()

    if scenario == "compliance":
        supplier_id = (supplier_id or os.getenv("FREIGHTVOICE_SUPPLIER_ID", "APPL-CAM-221")).upper()
        if supplier_id not in SUPPLIERS:
            logger.warning(f"Unknown supplier {supplier_id}, defaulting to APPL-CAM-221")
            supplier_id = "APPL-CAM-221"
        logger.info(f"Scenario: supplier compliance ({supplier_id})")
        return build_supplier_compliance(supplier_id)

    load_id = (load_id or os.getenv("FREIGHTVOICE_LOAD_ID", "TSLA-BAT-0412")).upper()
    if load_id not in SHIPMENTS:
        logger.warning(f"Unknown load {load_id}, defaulting to TSLA-BAT-0412")
        load_id = "TSLA-BAT-0412"
    logger.info(f"Scenario: carrier check-in ({load_id})")
    return build_carrier_checkin(load_id)
