"""FreightVoice Dashboard API + Outbound Call Orchestrator

Endpoints
─────────
  GET  /api/fleet                     All shipments + pre-computed risk scores
  POST /api/calls/trigger             Shipper dashboard → immediate outbound call
  POST /api/calls/risk                External: re-score a load, fire if ≥ 60
  POST /api/calls/signal              External signal (NOAA / traffic) → call
  POST /api/calls/milestone           Missed milestone → call
  POST /api/calls/schedule/start      Start the background scheduled checker
  POST /api/calls/schedule/stop       Stop the background scheduled checker
  GET  /outbound                      Twilio TwiML webhook (called when answered)
  POST /call-status                   Twilio status callback
  GET  /api/health                    Liveness check

Run:
    uv run uvicorn api_server:app --reload --port 8000
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from loguru import logger
from pydantic import BaseModel

from freight_backend import SHIPMENTS, fleet_overview
from freight_scenarios import _appointment_minutes_from_now
from outbound import (
    CallTrigger,
    _build_twiml,
    call_carrier,
    dashboard_triggered_call,
    external_signal_call,
    missed_milestone_call,
    risk_triggered_call,
    scheduler,
    _pipecat_ws_url,
)
from risk_scorer import compute_risk_score, fetch_weather_risk

load_dotenv(override=True)

_weather_cache: dict[str, float] = {}


async def _warm_weather_cache() -> None:
    lanes = list({s["lane"] for s in SHIPMENTS.values()})
    results = await asyncio.gather(
        *[fetch_weather_risk(lane) for lane in lanes],
        return_exceptions=True,
    )
    for lane, result in zip(lanes, results):
        _weather_cache[lane] = result if isinstance(result, float) else 0.20
    logger.info(f"Weather cache warmed for {len(_weather_cache)} lanes")


@asynccontextmanager
async def lifespan(_app: FastAPI):

    asyncio.create_task(_warm_weather_cache())

    if os.getenv("SCHEDULER_ENABLED", "false").lower() == "true":
        scheduler.start()

    yield

    scheduler.stop()


app = FastAPI(
    title="FreightVoice Dashboard API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_LIVE_CALLS_FILE = Path(__file__).parent / ".live_calls.json"


def _load_live_calls() -> dict[str, dict]:
    """Load persisted live-call state (survives --reload restarts)."""
    try:
        if _LIVE_CALLS_FILE.exists():
            return json.loads(_LIVE_CALLS_FILE.read_text())
    except Exception as exc:  
        logger.warning(f"Could not load live-call state: {exc}")
    return {}


def _save_live_calls() -> None:
    """Atomically persist live-call state so a reload can restore it."""
    try:
        tmp = _LIVE_CALLS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_live_calls))
        tmp.replace(_LIVE_CALLS_FILE)
    except Exception as exc: 
        logger.warning(f"Could not persist live-call state: {exc}")


_live_calls: dict[str, dict] = _load_live_calls()


def _baseline_risk(load_id: str, shipment: dict) -> dict:
    """Pre-call risk — historical signals only, no driver voice yet."""
    weather_risk     = _weather_cache.get(shipment["lane"], 0.20)
    deadline_minutes = _appointment_minutes_from_now(shipment["appointment"])

    result = compute_risk_score(
        sentiment="calm",
        historical_otd_rate=shipment["lane_on_time_rate"],
        eta_minutes_from_now=None,
        deadline_minutes_from_now=deadline_minutes,
        weather_risk=weather_risk,
        hourly_downtime_cost=shipment["hourly_downtime_cost"],
        production_line=shipment["production_line"],
        load_id=load_id,
    )
    return {
        "score": result.score,
        "level": result.level.value,
        "raw":   result.raw_score,
        "next_checkin_minutes": result.next_checkin_minutes,
        "signals": {
            name: {
                "label":        s.label,
                "contribution": s.contribution,
                "weight":       s.weight,
            }
            for name, s in result.signals.items()
        },
    }



@app.get("/api/fleet")
async def get_fleet():
    """Return all inbound shipments with pre-computed baseline risk scores
    AND any live call state captured during ongoing or recent calls.
    """
    shipments_out = []
    for load_id, shipment in SHIPMENTS.items():
        baseline = _baseline_risk(load_id, shipment)
        live = _live_calls.get(load_id)

        if live and live.get("live_risk"):
            lr = live["live_risk"]
            risk_display = {
                "score": lr["score"],
                "level": lr["level"],
                "raw":   lr.get("raw", 0),
                "next_checkin_minutes": lr.get("next_checkin_minutes", 0),
                "signals": lr.get("signals", baseline["signals"]),
                "source": "live",
                "baseline_score": baseline["score"],
                "baseline_level": baseline["level"],
            }
        else:
            risk_display = {
                **baseline,
                "source": "baseline",
                "baseline_score": baseline["score"],
                "baseline_level": baseline["level"],
            }

        shipments_out.append({
            "load_id":              load_id,
            "shipper":              shipment["shipper"],
            "carrier":              shipment["carrier"],
            "carrier_mc":           shipment.get("carrier_mc"),
            "driver_name":          shipment["driver_name"],
            "driver_phone":         shipment["driver_phone"],
            "commodity":            shipment["commodity"],
            "units":                shipment.get("units"),
            "weight_lbs":           shipment.get("weight_lbs"),
            "origin":               shipment["origin"],
            "lane":                 shipment["lane"],
            "dock":                 shipment["dock"],
            "gate":                 shipment["gate"],
            "appointment":          shipment["appointment"],
            "production_line":      shipment["production_line"],
            "hourly_downtime_cost": shipment["hourly_downtime_cost"],
            "lane_on_time_rate":    shipment["lane_on_time_rate"],
            "weather_risk":         _weather_cache.get(shipment["lane"], 0.20),
            "weather_description":  shipment.get("weather_risk"),
            "requires_temp_control":shipment["requires_temp_control"],
            "temp_range":           shipment.get("temp_range"),
            "hos_hours_remaining":  shipment.get("hos_hours_remaining"),
            "risk":                 risk_display,
            "live_call":            live,
        })

    return {
        "shipments": shipments_out,
        "summary":   fleet_overview(),
        "as_of":     datetime.now().isoformat(),
    }


@app.post("/api/calls/update")
async def call_update(payload: dict):
    """Voice bot pushes the latest call state here after each tool call.

    Body shape (all optional except load_id):
      {
        "load_id":           "TSLA-BAT-0412",
        "ts":                "2026-05-30T13:55:01.123",
        "stage":             "eta_confirmed" | "cargo_verified" | "dock_assigned"
                             | "risk_assessed" | "alerted" | "completed",
        "current_location":  "in Reno",
        "eta_text":          "about 20 out",
        "eta_minutes_from_now": 20,
        "driver_sentiment":  "calm",
        "cargo_ok":          true,
        "dock_notified":     true,
        "live_risk":         { "score": 72, "level": "CRITICAL", "signals": {...} },
        "logistics_alerted": true,
        "alert_action":      "Source backup carrier"
      }

    Updates are merged into the previous state for the same load_id so the
    dashboard always sees the latest full picture of the call.
    """
    load_id = payload.get("load_id")
    if not load_id:
        return {"ok": False, "message": "load_id required"}

    existing = _live_calls.get(load_id, {})
    merged = {**existing, **payload, "last_update": datetime.now().isoformat()}
    _live_calls[load_id] = merged
    _save_live_calls()
    logger.info(
        f"📡 Live update {load_id} stage={payload.get('stage', '?')} "
        f"keys={list(payload.keys())}"
    )
    return {"ok": True, "load_id": load_id, "stage": payload.get("stage")}


@app.get("/api/calls/live/{load_id}")
async def get_live_call(load_id: str):
    """Return just the live state for a single load (lower-latency polling)."""
    return _live_calls.get(load_id, {"load_id": load_id, "stage": None})


@app.post("/api/calls/clear/{load_id}")
async def clear_live_call(load_id: str):
    """Clear the live call state for a load — used by the dashboard reset button."""
    _live_calls.pop(load_id, None)
    _save_live_calls()
    return {"ok": True, "load_id": load_id}


_CALL_LOGS_DIR = Path(__file__).parent / ".call_logs"
_CALL_INDEX = _CALL_LOGS_DIR / "index.jsonl"


def _load_call_records() -> list[dict]:
    """Read persisted call records, newest first, deduped by call_id.

    The bot appends one line per finalized call to index.jsonl; a call_id can
    appear more than once (e.g. disconnect + graceful end), so we keep the last
    line written for each call_id.
    """
    if not _CALL_INDEX.exists():
        return []
    by_id: dict[str, dict] = {}
    for line in _CALL_INDEX.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        by_id[rec.get("call_id") or id(rec)] = rec
    records = list(by_id.values())
    records.sort(key=lambda r: r.get("completed_at") or "", reverse=True)
    return records


@app.get("/api/records")
async def get_records():
    """Every finalized call record, each scored by the local per-call evaluator.

    Powers the dashboard's records table — one row per call, any load, with its
    eval verdict. No external dependency; scoring is computed on read.
    """
    import call_eval

    records = _load_call_records()
    scored = call_eval.evaluate_records(records)

    rows = []
    for r in scored:
        state = r.get("scenario_state") or {}
        risk = state.get("risk_result") or {}
        shipment = SHIPMENTS.get(r.get("load_id") or "", {})
        rows.append({
            "call_id":          r.get("call_id"),
            "load_id":          r.get("load_id"),
            "carrier":          shipment.get("carrier"),
            "commodity":        shipment.get("commodity"),
            "from_number":      r.get("from_number"),
            "completed_at":     r.get("completed_at"),
            "ended_reason":     r.get("ended_reason"),
            "duration_secs":    r.get("duration_secs"),
            "num_turns":        r.get("num_turns"),
            "driver_sentiment": state.get("driver_sentiment"),
            "eta_minutes":      state.get("eta_minutes_from_now"),
            "risk_score":       risk.get("score"),
            "risk_level":       risk.get("level"),
            "logistics_alerted": bool(state.get("logistics_alerted")),
            "llm_ttfb_mean_ms": (r.get("latency") or {}).get("llm_ttfb_mean_ms"),
            "eval":             r.get("eval"),
            "transcript":       r.get("transcript_json", []),
        })

    n = len(rows)
    passed = sum(1 for row in rows if row["eval"]["verdict"] == "PASS")
    return {
        "records": rows,
        "summary": {
            "total": n,
            "passed": passed,
            "warned": sum(1 for row in rows if row["eval"]["verdict"] == "WARN"),
            "failed": sum(1 for row in rows if row["eval"]["verdict"] == "FAIL"),
            "pass_rate": round(100 * passed / n) if n else 0,
        },
        "as_of": datetime.now().isoformat(),
    }


class TriggerCallRequest(BaseModel):
    load_id: str
    scenario: Literal["carrier", "compliance"] = "carrier"


@app.post("/api/calls/trigger")
async def trigger_call(req: TriggerCallRequest):
    """Shipper-initiated call from the dashboard (Trigger 6)."""
    result = await dashboard_triggered_call(req.load_id)
    return result.to_dict()



class RiskUpdateRequest(BaseModel):
    load_id: str
    sentiment: str | None = None
    eta_minutes_from_now: int | None = None


@app.post("/api/calls/risk")
async def risk_update(req: RiskUpdateRequest):
    """Re-score a load and fire a call if risk ≥ 60 (Trigger 2).

    Called by: post-call webhooks, telematics integrations, internal cron.
    """
    if req.load_id not in SHIPMENTS:
        return {"ok": False, "message": f"Unknown load '{req.load_id}'"}

    shipment     = SHIPMENTS[req.load_id]
    weather_risk = await fetch_weather_risk(shipment["lane"])
    deadline_min = _appointment_minutes_from_now(shipment["appointment"])

    result = compute_risk_score(
        sentiment=req.sentiment or "calm",
        historical_otd_rate=shipment["lane_on_time_rate"],
        eta_minutes_from_now=req.eta_minutes_from_now,
        deadline_minutes_from_now=deadline_min,
        weather_risk=weather_risk,
        hourly_downtime_cost=shipment["hourly_downtime_cost"],
        production_line=shipment["production_line"],
        load_id=req.load_id,
    )

    call_result = await risk_triggered_call(req.load_id, result.score)
    return {
        "load_id":    req.load_id,
        "risk_score": result.score,
        "risk_level": result.level.value,
        "call_fired": call_result is not None,
        "call":       call_result.to_dict() if call_result else None,
    }


# ---------------------------------------------------------------------------
# Trigger 3: External signal — NOAA, traffic, customs
# ---------------------------------------------------------------------------

class ExternalSignalRequest(BaseModel):
    load_id: str
    signal_type: str        # "weather" | "traffic" | "customs" | ...
    description: str        # Human-readable context


@app.post("/api/calls/signal")
async def external_signal(req: ExternalSignalRequest):
    """Fire a call because of an external data signal (Trigger 3).

    Examples:
      - NOAA storm alert on the route
      - Google Maps 45-min delay on I-35
      - Customs hold at port of entry
    """
    result = await external_signal_call(req.load_id, req.signal_type, req.description)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Trigger 4: Missed milestone
# ---------------------------------------------------------------------------

class MilestoneRequest(BaseModel):
    load_id: str
    milestone: str      # e.g. "departure_confirmation", "en_route_checkpoint"


@app.post("/api/calls/milestone")
async def missed_milestone(req: MilestoneRequest):
    """Fire a call when a carrier misses a required check-in milestone (Trigger 4)."""
    result = await missed_milestone_call(req.load_id, req.milestone)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Trigger 1: Scheduled checker controls
# ---------------------------------------------------------------------------

@app.post("/api/calls/schedule/start")
async def schedule_start():
    """Start the background scheduled checker (Trigger 1)."""
    scheduler.start()
    return {"ok": True, "interval_seconds": scheduler.interval, "message": "Scheduler started"}


@app.post("/api/calls/schedule/stop")
async def schedule_stop():
    """Stop the background scheduled checker."""
    scheduler.stop()
    return {"ok": True, "message": "Scheduler stopped"}


# ---------------------------------------------------------------------------
# Twilio webhooks
# ---------------------------------------------------------------------------

@app.post("/incoming-call", response_class=PlainTextResponse)
async def incoming_call(request: Request):
    """Twilio Job 1 — INBOUND: carrier dials your Twilio number.

    Twilio POST-s here when a carrier calls your phone number.
    We return TwiML that opens a WebSocket stream into the FreightVoice bot.

    Console setup (one-time):
      Twilio Console → Phone Numbers → Active Numbers → <your number>
      Voice Configuration → "A call comes in"
        Webhook: https://<BASE_URL>/incoming-call  (HTTP POST)

    The load ID is unknown on inbound — FreightVoice will ask the driver to
    say the load number, which the LLM extracts and uses to look up context.
    Pass FREIGHTVOICE_LOAD_ID=unknown to let the bot handle discovery.
    """
    form     = await request.form()
    call_sid = form.get("CallSid", "")
    from_num = form.get("From", "unknown")
    to_num   = form.get("To", "")
    logger.info(f"📥 INBOUND CALL  sid={call_sid}  from={from_num}  to={to_num}")

    twiml = _build_twiml("unknown", CallTrigger.INBOUND, inbound=True)
    return PlainTextResponse(content=twiml, media_type="application/xml")


@app.get("/outbound", response_class=PlainTextResponse)
@app.post("/outbound", response_class=PlainTextResponse)
async def outbound_webhook(
    request: Request,
    load: str = Query(default=""),
    trigger: str = Query(default="dashboard"),
):
    """Twilio Job 2 — OUTBOUND: FreightVoice called the carrier, they answered.

    Twilio fetches TwiML here when the outbound call is picked up.
    We return TwiML that streams audio into the FreightVoice bot.

    The load ID + trigger are passed as query params by call_carrier():
      BASE_URL/outbound?load=TSLA-BAT-0412&trigger=risk_threshold
    """
    # Twilio also sends form fields on POST — prefer query params
    if not load:
        form = await request.form()
        load = form.get("load", "")

    try:
        call_trigger = CallTrigger(trigger)
    except ValueError:
        call_trigger = CallTrigger.DASHBOARD

    logger.info(f"📤 OUTBOUND ANSWERED  load={load}  trigger={trigger}")
    twiml = _build_twiml(load, call_trigger, inbound=False)
    return PlainTextResponse(content=twiml, media_type="application/xml")


@app.post("/call-status")
async def call_status(request: Request):
    """Twilio status callback — logs every call lifecycle event."""
    form        = await request.form()
    call_sid    = form.get("CallSid", "")
    status      = form.get("CallStatus", "")
    direction   = form.get("Direction", "")
    to          = form.get("To", "")
    from_num    = form.get("From", "")
    duration    = form.get("CallDuration", "")
    logger.info(
        f"📋 CALL STATUS  sid={call_sid}  [{direction}]  {from_num}→{to}  "
        f"status={status}  duration={duration}s"
    )
    return PlainTextResponse("OK")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    pipecat_ws = _pipecat_ws_url("healthcheck", CallTrigger.DASHBOARD)
    twilio_ok  = all([
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN"),
        os.getenv("TWILIO_PHONE_NUMBER"),
    ])
    base_url = os.getenv("BASE_URL", "").strip()
    return {
        "ok":   True,
        "twilio": {
            "configured":     twilio_ok,
            "phone_number":   os.getenv("TWILIO_PHONE_NUMBER", "not set"),
            "inbound_webhook":  f"{base_url}/incoming-call" if base_url else "BASE_URL not set",
            "outbound_webhook": f"{base_url}/outbound"      if base_url else "BASE_URL not set",
            "status_callback":  f"{base_url}/call-status"   if base_url else "BASE_URL not set",
        },
        "pipecat": {
            "ws_url":         pipecat_ws or "not configured — using <Say> fallback",
            "cloud_org":      os.getenv("PIPECAT_ORG_NAME", "not set"),
            "local_ws":       os.getenv("PIPECAT_WS_URL",   "not set"),
        },
        "demo": {
            "active":         bool(os.getenv("DEMO_CARRIER_PHONE")),
            "phone":          os.getenv("DEMO_CARRIER_PHONE", "not set"),
        },
        "scheduler": {
            "running":          scheduler._running,
            "interval_seconds": scheduler.interval,
        },
        "weather_cache_lanes": len(_weather_cache),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
