"""Per-call evaluation — score one real call record the way eval_agent.py
scores a scripted persona, but from a *persisted* call (any load, not just the
demo one).

A call record is what ``post_call.finalize_call`` writes to ``.call_logs/``:
transcript turns (with ``[action: <tool>]`` markers for tool calls), per-service
latency, ended reason, and the final ``scenario_state`` (sentiment, cargo, dock,
risk_result, logistics_alerted).

``evaluate_record`` turns that into a flat verdict the dashboard renders as a
row: a list of named checks (pass/fail/warn), an overall PASS/WARN/FAIL, and a
0–100 quality score. It mirrors eval_agent's dimensions — sentiment captured,
required steps completed, alert fired iff the risk model demanded it, call ended
cleanly — plus a latency check.

This is the LOCAL eval. It runs offline, per record, with no Cekura dependency.
"""

from __future__ import annotations

import re

_VALID_SENTIMENTS = {"confident", "calm", "uncertain", "frustrated"}

_LLM_TTFB_WARN_MS = 3500


def _actions(record: dict) -> list[str]:
    """Tool names the agent invoked, parsed from `[action: a, b]` transcript turns."""
    names: list[str] = []
    for turn in record.get("transcript_json", []):
        if turn.get("role") != "assistant":
            continue
        m = re.match(r"\[action:\s*(.+)\]", (turn.get("content") or "").strip())
        if m:
            names.extend(n.strip() for n in m.group(1).split(",") if n.strip())
    return names


def _check(name: str, ok: bool | None, *, label: str, critical: bool = True) -> dict:
    """ok=True pass, ok=False fail, ok=None not-applicable (skipped)."""
    if ok is None:
        status = "na"
    elif ok:
        status = "pass"
    else:
        status = "fail" if critical else "warn"
    return {"name": name, "label": label, "status": status, "critical": critical}


def evaluate_record(record: dict) -> dict:
    """Score one persisted call record. Returns a JSON-safe verdict dict."""
    state = record.get("scenario_state") or {}
    actions = set(_actions(record))
    risk = state.get("risk_result") or {}
    must_alert = bool(risk.get("must_alert"))
    alerted = bool(state.get("logistics_alerted"))

    checks: list[dict] = []

    sentiment = state.get("driver_sentiment")
    checks.append(
        _check(
            "sentiment",
            (sentiment in _VALID_SENTIMENTS) or ("confirm_eta" in actions),
            label="Driver sentiment captured",
        )
    )

    checks.append(
        _check(
            "eta",
            ("confirm_eta" in actions) or (state.get("eta_minutes_from_now") is not None),
            label="ETA confirmed",
        )
    )

    checks.append(
        _check(
            "cargo",
            ("verify_cargo_condition" in actions) or (state.get("cargo_ok") is not None),
            label="Cargo condition verified",
            critical=False,
        )
    )

    checks.append(
        _check(
            "dock",
            ("assign_dock" in actions) or bool(state.get("dock_notified")),
            label="Dock assigned",
            critical=False,
        )
    )

    checks.append(
        _check("risk", ("assess_risk" in actions) or bool(risk), label="Risk assessed")
    )

    if must_alert:
        checks.append(_check("alert", alerted, label="Escalated when risk demanded it"))
    elif risk:
        checks.append(
            _check("alert", not alerted, label="Did not over-escalate (low risk)")
        )
    else:
        checks.append(_check("alert", None, label="Alert handling (no risk run)"))

    checks.append(
        _check(
            "completion",
            record.get("ended_reason") == "completed",
            label="Call ended cleanly",
        )
    )

    llm_ms = (record.get("latency") or {}).get("llm_ttfb_mean_ms")
    if llm_ms is not None:
        checks.append(
            _check(
                "latency",
                llm_ms <= _LLM_TTFB_WARN_MS,
                label=f"LLM TTFB {round(llm_ms)}ms",
                critical=False,
            )
        )

    scored = [c for c in checks if c["status"] != "na"]
    passed = sum(1 for c in scored if c["status"] == "pass")
    score = round(100 * passed / len(scored)) if scored else 0

    critical_fail = any(c["status"] == "fail" and c["critical"] for c in checks)
    any_warn = any(c["status"] == "warn" for c in checks)
    verdict = "FAIL" if critical_fail else ("WARN" if any_warn else "PASS")

    return {
        "verdict": verdict,
        "score": score,
        "checks": checks,
        "passed": passed,
        "total": len(scored),
    }


def evaluate_records(records: list[dict]) -> list[dict]:
    """Evaluate a list of records, returning each record enriched with `eval`."""
    return [{**r, "eval": evaluate_record(r)} for r in records]
