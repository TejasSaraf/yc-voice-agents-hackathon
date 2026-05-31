"""FreightVoice evaluation harness — test cases, scoring, and latency.

Two modes:

1. OFFLINE (default) — drives the *real* Nemotron LLM (same system prompt and
   tool contract as production, via ``build_scenario()``) through a set of
   scripted driver personas. No audio / Twilio / pipecat needed: scripted user
   turns go in, the model's tool calls + replies come out, tools are simulated.
   For each persona we score:
     • sentiment      — did confirm_eta classify the driver correctly?
     • tools          — were the required tools called (eta, cargo, dock, risk)?
     • alert          — did it alert logistics iff the risk model said must_alert?
     • completion     — did it end the call cleanly?
   and we measure LLM latency per turn (mean / p90), so you can A/B
   ``NEMOTRON_ENABLE_THINKING=true|false`` and see the cost.

   Results print as a scorecard and are written to ``server/.eval_results/``.

2. CEKURA (``--cekura``) — triggers Cekura evaluator scenarios (cloud, simulated
   callers over voice) against the live agent and polls pass/fail. Requires
   CEKURA_API_KEY + CEKURA_AGENT_ID and scenario ids.

Usage:
    uv run eval_agent.py                      # run all offline personas once
    uv run eval_agent.py --persona late_rain  # one persona
    uv run eval_agent.py --repeat 3           # 3x each (latency stability)
    uv run eval_agent.py --cekura --scenario-ids 30,31
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv

load_dotenv(override=True)

RESULTS_DIR = Path(__file__).parent / ".eval_results"


# ── Tool contract (mirrors freight_scenarios carrier check-in) ───────────────
# Schemas the model is offered. Kept explicit here so the harness is independent
# of pipecat's tool adapter and can run standalone.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "confirm_eta",
            "description": "Record the driver's location, ETA, and your read of their tone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_location": {"type": "string"},
                    "eta": {"type": "string"},
                    "driver_sentiment": {
                        "type": "string",
                        "enum": ["confident", "calm", "uncertain", "frustrated"],
                    },
                    "eta_minutes_from_now": {"type": ["integer", "null"]},
                },
                "required": ["driver_sentiment"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_cargo_condition",
            "description": "Verify the load is sealed and temperature-controlled.",
            "parameters": {
                "type": "object",
                "properties": {"sealed": {"type": "boolean"}, "notes": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assign_dock",
            "description": "Assign a receiving dock and gate for the driver.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "assess_risk",
            "description": "Run the predictive risk model for this load. Returns must_alert.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "alert_logistics_team",
            "description": "Alert the shipper's logistics team with a recommended action.",
            "parameters": {
                "type": "object",
                "properties": {"recommended_action": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "End the call after a short sign-off.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


@dataclass
class Persona:
    """A scripted driver + the outcomes we expect from the agent."""

    name: str
    description: str
    turns: list[str]  # consecutive driver utterances (advanced as agent asks)
    expect_sentiment: set[str]
    expect_alert: bool  # should the agent alert logistics? (drives assess_risk result)
    expect_tools: set[str] = field(
        default_factory=lambda: {"confirm_eta", "assess_risk", "end_call"}
    )


PERSONAS: list[Persona] = [
    Persona(
        name="late_rain",
        description="Vague, hedging driver ~45 min late in rain — should escalate.",
        turns=[
            "Yeah, I'm still outside Sacramento on I-80. Traffic's bad and it's raining.",
            "I'm probably like 45 minutes out, maybe more.",
            "Yeah, it's sealed, reefer's running fine.",
            "Okay, sounds good.",
        ],
        expect_sentiment={"uncertain", "frustrated"},
        expect_alert=True,
        expect_tools={"confirm_eta", "verify_cargo_condition", "assess_risk", "end_call"},
    ),
    Persona(
        name="on_time_confident",
        description="Confident, specific, on-time driver — no escalation.",
        turns=[
            "Hey, yeah — I'm about ten minutes out, just got off the freeway at the Dock 12 gate.",
            "Seal's intact, temperature's right at spec.",
            "Got it, Dock 12, gate 4. Thanks.",
        ],
        expect_sentiment={"confident", "calm"},
        expect_alert=False,
        expect_tools={"confirm_eta", "verify_cargo_condition", "assess_risk", "end_call"},
    ),
    Persona(
        name="frustrated_breakdown",
        description="Frustrated driver with a breakdown, no clear ETA — must escalate.",
        turns=[
            "Honestly man, I'm stuck. Truck threw a code and I'm pulled over on the shoulder.",
            "I have no idea, could be hours. Waiting on roadside.",
            "Load's fine, it's sealed, but I'm not moving right now.",
            "Yeah, whatever, do what you gotta do.",
        ],
        expect_sentiment={"frustrated", "uncertain"},
        expect_alert=True,
        expect_tools={"confirm_eta", "assess_risk", "alert_logistics_team", "end_call"},
    ),
]


def _client():
    from openai import OpenAI

    return OpenAI(
        api_key=os.getenv("NEMOTRON_LLM_API_KEY", "EMPTY"),
        base_url=os.getenv("NEMOTRON_LLM_URL", "http://localhost:8000/v1"),
    )


def _model() -> str:
    return os.getenv("NEMOTRON_LLM_MODEL", "nvidia/nemotron-3-super")


def _extra_body() -> dict:
    enable_thinking = os.getenv("NEMOTRON_ENABLE_THINKING", "true").lower() == "true"
    return {"chat_template_kwargs": {"enable_thinking": enable_thinking}}


def _simulate_tool(name: str, args: dict, persona: Persona) -> str:
    """Return a deterministic tool result so the conversation can proceed."""
    if name == "assess_risk":
        # The model must FOLLOW must_alert. Drive it from the persona so the
        # alert step is a clean test of instruction adherence.
        if persona.expect_alert:
            return json.dumps(
                {
                    "risk_level": "CRITICAL",
                    "score": 78,
                    "must_alert": True,
                    "recommended_action": "Source backup carrier, hold dock",
                }
            )
        return json.dumps({"risk_level": "LOW", "score": 18, "must_alert": False})
    if name == "confirm_eta":
        return json.dumps({"ok": True, "next": "Verify cargo, then assign dock and assess risk."})
    if name == "assign_dock":
        return json.dumps({"ok": True, "dock": "Dock 12", "gate": "Gate 4"})
    return json.dumps({"ok": True})


def _strip_think(text: str | None) -> str:
    if not text:
        return ""
    import re

    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


@dataclass
class CaseResult:
    persona: str
    sentiment_recorded: str | None
    tools_called: list[str]
    alerted: bool
    completed: bool
    sentiment_ok: bool
    tools_ok: bool
    alert_ok: bool
    passed: bool
    turn_latencies: list[float]
    transcript: list[dict]

    @property
    def mean_latency(self) -> float:
        return mean(self.turn_latencies) if self.turn_latencies else 0.0

    @property
    def p90_latency(self) -> float:
        if not self.turn_latencies:
            return 0.0
        s = sorted(self.turn_latencies)
        return s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]


def run_persona(persona: Persona, system_prompt: str, greeting: str, max_turns: int = 14) -> CaseResult:
    client = _client()
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": greeting},
    ]
    script = list(persona.turns)
    tools_called: list[str] = []
    sentiment_recorded: str | None = None
    alerted = False
    completed = False
    latencies: list[float] = []
    transcript: list[dict] = []

    for _ in range(max_turns):
        t0 = time.time()
        resp = client.chat.completions.create(
            model=_model(),
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
            extra_body=_extra_body(),
        )
        latencies.append(time.time() - t0)
        msg = resp.choices[0].message

        if msg.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                tools_called.append(name)
                transcript.append({"role": "assistant", "content": f"[action: {name}]"})
                if name == "confirm_eta" and sentiment_recorded is None:
                    sentiment_recorded = args.get("driver_sentiment")
                if name == "alert_logistics_team":
                    alerted = True
                if name == "end_call":
                    completed = True
                result = _simulate_tool(name, args, persona)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            if completed:
                break
            continue  # let the model continue after seeing tool results

        # Spoken reply (a question / statement) → advance the driver script.
        content = _strip_think(msg.content)
        messages.append({"role": "assistant", "content": msg.content or ""})
        if content:
            transcript.append({"role": "assistant", "content": content})
        if script:
            driver = script.pop(0)
            messages.append({"role": "user", "content": driver})
            transcript.append({"role": "user", "content": driver})
        else:
            break

    sentiment_ok = sentiment_recorded in persona.expect_sentiment
    tools_ok = persona.expect_tools.issubset(set(tools_called))
    alert_ok = alerted == persona.expect_alert
    passed = sentiment_ok and tools_ok and alert_ok and completed

    return CaseResult(
        persona=persona.name,
        sentiment_recorded=sentiment_recorded,
        tools_called=tools_called,
        alerted=alerted,
        completed=completed,
        sentiment_ok=sentiment_ok,
        tools_ok=tools_ok,
        alert_ok=alert_ok,
        passed=passed,
        turn_latencies=latencies,
        transcript=transcript,
    )


def score_prompt(system_prompt: str, greeting: str, repeat: int = 1) -> dict:
    """Run every persona against a GIVEN system prompt and return a summary.

    Used by auto_improve.py to compare a candidate prompt against the current
    one on the same regression suite. Returns pass count, per-persona verdicts,
    and mean LLM latency.
    """
    results: list[CaseResult] = []
    for persona in PERSONAS:
        for _ in range(repeat):
            results.append(run_persona(persona, system_prompt, greeting))
    all_lat = [l for r in results for l in r.turn_latencies]
    return {
        "passed": sum(1 for r in results if r.passed),
        "total": len(results),
        "by_persona": {r.persona: r.passed for r in results},
        "mean_latency": mean(all_lat) if all_lat else 0.0,
    }


def _print_scorecard(results: list[CaseResult]) -> None:
    print("\n" + "=" * 74)
    print("FreightVoice eval scorecard  (thinking={})".format(os.getenv("NEMOTRON_ENABLE_THINKING", "true")))
    print("=" * 74)
    header = f"{'persona':<22}{'pass':<6}{'sentiment':<22}{'alert':<7}{'mean_s':<8}{'p90_s':<7}"
    print(header)
    print("-" * 74)
    for r in results:
        sent = f"{r.sentiment_recorded or '-'}{'' if r.sentiment_ok else ' ✗'}"
        print(
            f"{r.persona:<22}{('PASS' if r.passed else 'FAIL'):<6}{sent:<22}"
            f"{('ok' if r.alert_ok else 'BAD'):<7}{r.mean_latency:<8.2f}{r.p90_latency:<7.2f}"
        )
    n_pass = sum(1 for r in results if r.passed)
    all_lat = [l for r in results for l in r.turn_latencies]
    print("-" * 74)
    print(f"PASS {n_pass}/{len(results)}   LLM turn latency: mean {mean(all_lat):.2f}s" if all_lat else "")
    print("=" * 74 + "\n")


def run_offline(args) -> int:
    _tools, system_prompt, greeting = _build_prompt()
    selected = [p for p in PERSONAS if not args.persona or p.name == args.persona]
    if not selected:
        print(f"No persona named '{args.persona}'. Available: {[p.name for p in PERSONAS]}")
        return 2

    results: list[CaseResult] = []
    for persona in selected:
        for i in range(args.repeat):
            print(f"▶ {persona.name} (run {i + 1}/{args.repeat}) — {persona.description}")
            try:
                results.append(run_persona(persona, system_prompt, greeting))
            except Exception as exc:
                print(f"  ERROR running {persona.name}: {exc}")

    _print_scorecard(results)

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"eval-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(
        json.dumps(
            {
                "thinking": os.getenv("NEMOTRON_ENABLE_THINKING", "true"),
                "model": _model(),
                "results": [r.__dict__ for r in results],
            },
            indent=2,
            default=lambda o: list(o) if isinstance(o, set) else str(o),
        )
    )
    print(f"Wrote {out}")
    return 0 if all(r.passed for r in results) else 1


def _build_prompt():
    import freight_scenarios as fs

    return fs.build_scenario()


def run_cekura(args) -> int:
    import cekura_client

    if not cekura_client.is_configured():
        print("CEKURA_API_KEY not set. See .env.example.")
        return 2
    if not args.scenario_ids:
        print("--scenario-ids is required for --cekura (comma-separated).")
        return 2
    ids = [int(x) for x in args.scenario_ids.split(",") if x.strip()]
    print(f"Triggering Cekura scenarios {ids} (mode={args.mode})…")
    result = cekura_client.run_scenarios(ids, frequency=args.repeat, mode=args.mode)
    result_id = result.get("id")
    print(f"Started result {result_id}, status={result.get('status')}")
    if not result_id:
        print(json.dumps(result, indent=2))
        return 1

    # Poll for completion.
    for _ in range(args.timeout // 10):
        time.sleep(10)
        r = cekura_client.get_result(result_id)
        status = r.get("status")
        print(f"  status={status} success_rate={r.get('success_rate')}")
        if status in ("completed", "failed", "errored"):
            print(json.dumps(r, indent=2)[:2000])
            return 0 if r.get("success_rate", 0) and float(r["success_rate"]) >= 100 else 1
    print("Timed out waiting for Cekura result.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="FreightVoice agent evaluation")
    ap.add_argument("--persona", help="Run only this offline persona")
    ap.add_argument("--repeat", type=int, default=1, help="Runs per case")
    ap.add_argument("--cekura", action="store_true", help="Run Cekura cloud scenarios instead")
    ap.add_argument("--scenario-ids", help="Comma-separated Cekura scenario ids (--cekura)")
    ap.add_argument("--mode", default="voice", help="Cekura run mode: voice|pipecat|pipecat_v2")
    ap.add_argument("--timeout", type=int, default=600, help="Cekura poll timeout seconds")
    args = ap.parse_args()
    return run_cekura(args) if args.cekura else run_offline(args)


if __name__ == "__main__":
    raise SystemExit(main())
