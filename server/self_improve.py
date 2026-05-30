"""Self-improvement loop for FreightVoice.

Run this after a batch of calls to turn real conversations into agent
improvements. Two backends:

1. CEKURA (preferred, if CEKURA_API_KEY + CEKURA_AGENT_ID set) — calls
   ``/observability/v1/call-logs/improve_prompt/``, which reads recent
   production call logs + their metric outcomes and proposes concrete
   system-prompt edits. This is the managed "diagnose failing evals → propose
   prompt fix" loop.

2. LOCAL fallback (no Cekura needed) — analyzes the call records written by
   ``post_call.finalize_call`` under ``server/.call_logs/`` and prints a
   data-driven diagnosis: latency outliers, sentiment distribution, calls that
   went CRITICAL without an alert, and likely transcription/echo issues
   (repeated near-identical turns). Useful in the demo and offline.

Usage:
    uv run self_improve.py                 # auto: Cekura if configured, else local
    uv run self_improve.py --local         # force local analysis
    uv run self_improve.py --call-logs 20  # reevaluate up to 20 recent Cekura logs
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

CALL_LOGS_DIR = Path(__file__).parent / ".call_logs"
_INDEX = CALL_LOGS_DIR / "index.jsonl"


def _load_records() -> list[dict]:
    if not _INDEX.exists():
        return []
    records = []
    for line in _INDEX.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def _similar(a: str, b: str) -> bool:
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted([a, b], key=len)
    return shorter in longer and len(shorter) >= 6


def run_local() -> int:
    records = _load_records()
    if not records:
        print(f"No call records found in {CALL_LOGS_DIR}. Place some calls first.")
        return 2

    print("=" * 72)
    print(f"FreightVoice self-improve — local analysis of {len(records)} call(s)")
    print("=" * 72)

    # Latency
    llm_lat = [
        r["latency"]["llm_ttfb_mean_ms"]
        for r in records
        if r.get("latency", {}).get("llm_ttfb_mean_ms")
    ]
    if llm_lat:
        avg = sum(llm_lat) / len(llm_lat)
        worst = max(llm_lat)
        print(f"\nLLM TTFB: avg {avg:.0f}ms, worst {worst:.0f}ms across {len(llm_lat)} calls")
        if avg > 1500:
            print(
                "  ⚠ High LLM time-to-first-token. Consider NEMOTRON_ENABLE_THINKING=false\n"
                "    for lower latency, or shorten the system prompt. Re-check with eval_agent.py."
            )

    # Sentiment distribution + missed alerts
    sentiments = Counter()
    missed_alerts = 0
    repeated = 0
    for r in records:
        state = r.get("scenario_state") or {}
        s = state.get("driver_sentiment")
        if s:
            sentiments[s] += 1
        if (state.get("risk_result") or {}).get("must_alert") and not state.get(
            "logistics_alerted"
        ):
            missed_alerts += 1
        # repeated/echo detection on transcript
        turns = r.get("transcript_json", [])
        for i in range(1, len(turns)):
            if turns[i]["role"] == turns[i - 1]["role"] and _similar(
                turns[i]["content"], turns[i - 1]["content"]
            ):
                repeated += 1
                break

    if sentiments:
        print(f"\nDriver sentiment mix: {dict(sentiments)}")
    if missed_alerts:
        print(
            f"\n  ⚠ {missed_alerts} call(s) hit must_alert but did NOT call alert_logistics_team."
        )
        print(
            "    Strengthen step 4 of the system prompt: 'If assess_risk returns\n"
            "    must_alert=true you MUST call alert_logistics_team before sign-off.'"
        )
    if repeated:
        print(
            f"\n  ⚠ {repeated} call(s) show consecutive near-duplicate turns (possible echo\n"
            "    or chain-of-thought leak). Verify ThinkTagFilter + AlwaysUserMuteStrategy."
        )

    print("\nSuggested next steps:")
    print("  • Run `uv run eval_agent.py` to regression-test against scripted personas.")
    print("  • Set CEKURA_API_KEY + CEKURA_AGENT_ID to get LLM-judge-backed prompt rewrites.")
    print("=" * 72)
    return 0


def run_cekura(call_logs: int) -> int:
    import cekura_client
    import freight_scenarios

    _tools, system_prompt, _greeting = freight_scenarios.build_scenario()

    print(f"Asking Cekura to improve the prompt from the last {call_logs} call log(s)…")
    try:
        result = cekura_client.improve_prompt_from_calls(
            prompt=system_prompt, call_logs=call_logs
        )
    except Exception as exc:
        print(f"Cekura improve_prompt failed ({exc}). Falling back to local analysis.\n")
        return run_local()

    print("=" * 72)
    improved = (
        result.get("improved_prompt")
        or result.get("prompt")
        or result.get("suggested_prompt")
    )
    issues = result.get("issues") or result.get("categorized_issues")
    if issues:
        print("Issues Cekura identified:")
        print(json.dumps(issues, indent=2)[:4000])
    if improved:
        print("\n--- Cekura suggested system prompt ---\n")
        print(improved)
        out = Path(__file__).parent / ".eval_results" / "cekura_suggested_prompt.txt"
        out.parent.mkdir(exist_ok=True)
        out.write_text(improved if isinstance(improved, str) else json.dumps(improved, indent=2))
        print(f"\nSaved to {out}. Review, then paste into freight_scenarios.py.")
    else:
        print("Cekura response (no prompt field found):")
        print(json.dumps(result, indent=2)[:4000])
    print("=" * 72)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="FreightVoice self-improvement loop")
    ap.add_argument("--local", action="store_true", help="Force local analysis (skip Cekura)")
    ap.add_argument(
        "--call-logs",
        type=int,
        default=10,
        help="How many recent Cekura call logs to reevaluate (capped at available)",
    )
    args = ap.parse_args()

    import cekura_client

    if not args.local and cekura_client.is_configured() and cekura_client.agent_id():
        return run_cekura(args.call_logs)
    return run_local()


if __name__ == "__main__":
    raise SystemExit(main())
