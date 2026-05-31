"""Gated self-improvement loop for the carrier system prompt.

This is the SAFE version of "improve the prompt after evals": it never edits a
live prompt blindly. Instead it

  1. reads the current carrier prompt template (prompt_store),
  2. summarizes issues from recent real call records (call_eval),
  3. asks the LLM to produce a CANDIDATE template (placeholders + tools preserved),
  4. validates the candidate, then scores BOTH current and candidate on the same
     regression suite (eval_agent personas, driving the real Nemotron model), and
  5. applies the candidate ONLY if it strictly beats the current prompt with no
     per-persona regression. Otherwise it keeps the current prompt.

The applied prompt is written as an override in prompt_store; the bot picks it
up on the next call. A backup of the previous template is kept, and `--revert`
restores the shipped default.

Usage:
    uv run auto_improve.py              # generate → score → apply if better
    uv run auto_improve.py --dry-run    # generate → score → report only (no write)
    uv run auto_improve.py --repeat 2   # score each persona twice (less variance)
    uv run auto_improve.py --show       # print the active template
    uv run auto_improve.py --revert     # drop the override, restore default
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

EVAL_LOAD = "TSLA-BAT-0412"
_CHANGELOG = Path(__file__).parent / ".prompt_overrides" / "changelog.jsonl"


def _issues_summary(limit: int = 10) -> str:
    """Summarize what went wrong on recent real calls, for the rewrite prompt."""
    import call_eval
    import self_improve

    records = self_improve._load_records()[-limit:]
    if not records:
        return "No real call records yet. Improve clarity and concision generally."

    failed_checks: Counter = Counter()
    sentiments: Counter = Counter()
    snippets: list[str] = []
    for r in records:
        ev = call_eval.evaluate_record(r)
        for c in ev["checks"]:
            if c["status"] in ("fail", "warn"):
                failed_checks[c["label"]] += 1
        s = (r.get("scenario_state") or {}).get("driver_sentiment")
        if s:
            sentiments[s] += 1
        if ev["verdict"] != "PASS":
            turns = [t.get("content", "") for t in r.get("transcript_json", [])][:6]
            snippets.append(" | ".join(turns)[:300])

    lines = [f"Calls analyzed: {len(records)}", f"Driver sentiments: {dict(sentiments)}"]
    if failed_checks:
        lines.append("Failed/weak eval checks: " + json.dumps(dict(failed_checks)))
    else:
        lines.append("No failing checks recently — focus on concision and reliability.")
    if snippets:
        lines.append("Example non-passing call turns:\n  - " + "\n  - ".join(snippets[:3]))
    return "\n".join(lines)


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: t.rfind("```")]
    return t.strip()


def generate_candidate(current: str, issues: str) -> str | None:
    """Ask the LLM for an improved template. Returns the candidate or None."""
    import eval_agent

    system = (
        "You improve the system prompt of a PRODUCTION voice agent that places "
        "OUTBOUND phone calls to freight carriers. Output ONLY the improved prompt "
        "template text — no markdown, no code fences, no commentary."
    )
    placeholders = " ".join("{" + p + "}" for p in sorted(__import__("prompt_store").PLACEHOLDERS))
    user = (
        "Here is the CURRENT prompt template. It uses str.format placeholders that "
        "must be preserved EXACTLY:\n"
        f"{placeholders}\n\n"
        "=== CURRENT TEMPLATE ===\n"
        f"{current}\n\n"
        "=== OBSERVED ISSUES FROM RECENT CALLS ===\n"
        f"{issues}\n\n"
        "Rewrite the template to reduce those issues. HARD REQUIREMENTS:\n"
        "- Keep every placeholder above, spelled exactly, at least once.\n"
        "- Keep the ordered call procedure and EVERY tool name: confirm_eta, "
        "verify_cargo_condition, assign_dock, assess_risk, alert_logistics_team, end_call.\n"
        "- Keep it concise and natural for speech. Do not invent new tools or fields.\n"
        "Output ONLY the template text."
    )
    client = eval_agent._client()
    resp = client.chat.completions.create(
        model=eval_agent._model(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.4,
        extra_body=eval_agent._extra_body(),
    )
    return _strip_fences(eval_agent._strip_think(resp.choices[0].message.content)) or None


def _formats_for_all_loads(template: str) -> tuple[bool, str]:
    """Ensure the template renders for every carrier load, not just the eval one."""
    import freight_scenarios as fs
    from freight_backend import SHIPMENTS

    for load_id, sh in SHIPMENTS.items():
        if "driver_name" not in sh:
            continue  # supplier record, not a carrier load
        try:
            template.format(**fs._carrier_fields(load_id))
        except Exception as exc:
            return False, f"fails to render for {load_id}: {exc}"
    return True, "ok"


def _log(entry: dict) -> None:
    _CHANGELOG.parent.mkdir(exist_ok=True)
    with _CHANGELOG.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def run(dry_run: bool, repeat: int) -> int:
    import eval_agent
    import freight_scenarios as fs
    import prompt_store

    current = prompt_store.load_template()
    fields = fs._carrier_fields(EVAL_LOAD)
    _tools, _sys, greeting = fs.build_scenario(load_id=EVAL_LOAD)

    print("=" * 72)
    print("FreightVoice auto-improve — gated prompt self-improvement")
    print(f"Active prompt: {'OVERRIDE' if prompt_store.is_override_active() else 'default'}")
    print("=" * 72)

    print("\n1) Summarizing recent call issues…")
    issues = _issues_summary()
    print("   " + issues.replace("\n", "\n   "))

    print("\n2) Generating a candidate prompt (LLM rewrite)…")
    try:
        candidate = generate_candidate(current, issues)
    except Exception as exc:
        print(f"   Candidate generation failed: {exc}")
        return 1
    if not candidate:
        print("   No candidate produced. Keeping current prompt.")
        return 0

    ok, reason = prompt_store.validate(candidate)
    if not ok:
        print(f"   ✗ Candidate rejected (invalid): {reason}. Keeping current prompt.")
        _log({"ts": datetime.now().isoformat(), "result": "rejected_invalid", "reason": reason})
        return 0
    ok, reason = _formats_for_all_loads(candidate)
    if not ok:
        print(f"   ✗ Candidate rejected: {reason}. Keeping current prompt.")
        _log({"ts": datetime.now().isoformat(), "result": "rejected_render", "reason": reason})
        return 0
    print("   ✓ Candidate is valid (placeholders + tools + renders for all loads).")

    print(f"\n3) Scoring CURRENT prompt on {len(eval_agent.PERSONAS)} personas (repeat={repeat})…")
    cur_score = eval_agent.score_prompt(prompt_store.render(current, fields), greeting, repeat)
    print(f"   current: {cur_score['passed']}/{cur_score['total']}  "
          f"by_persona={cur_score['by_persona']}  mean_latency={cur_score['mean_latency']:.2f}s")

    print(f"\n4) Scoring CANDIDATE prompt (repeat={repeat})…")
    cand_score = eval_agent.score_prompt(prompt_store.render(candidate, fields), greeting, repeat)
    print(f"   candidate: {cand_score['passed']}/{cand_score['total']}  "
          f"by_persona={cand_score['by_persona']}  mean_latency={cand_score['mean_latency']:.2f}s")

    # Gate: strict improvement, and no persona that passed now may regress.
    regressed = [
        p for p, ok_now in cur_score["by_persona"].items()
        if ok_now and not cand_score["by_persona"].get(p, False)
    ]
    improved = cand_score["passed"] > cur_score["passed"]

    print("\n5) Decision:")
    entry = {
        "ts": datetime.now().isoformat(),
        "current": cur_score["passed"], "candidate": cand_score["passed"],
        "total": cur_score["total"], "regressed": regressed,
    }
    if regressed:
        print(f"   ✗ REJECTED — candidate regresses persona(s): {regressed}. Keeping current.")
        entry["result"] = "rejected_regression"
    elif not improved:
        print(f"   = NO CHANGE — candidate ({cand_score['passed']}) does not beat current "
              f"({cur_score['passed']}). Keeping current prompt.")
        entry["result"] = "no_improvement"
    elif dry_run:
        print(f"   ✓ Candidate IMPROVES ({cur_score['passed']} → {cand_score['passed']}) "
              "but --dry-run set; not writing. Candidate below:\n")
        print(candidate)
        entry["result"] = "improved_dryrun"
    else:
        saved, why = prompt_store.save_template(candidate)
        if saved:
            print(f"   ✓ APPLIED — candidate beat current ({cur_score['passed']} → "
                  f"{cand_score['passed']}). Override written; bot uses it next call.")
            entry["result"] = "applied"
        else:
            print(f"   ✗ Could not save candidate: {why}. Keeping current.")
            entry["result"] = "save_failed"
    _log(entry)
    print("=" * 72)
    return 0


def main() -> int:
    import prompt_store

    ap = argparse.ArgumentParser(description="Gated prompt self-improvement")
    ap.add_argument("--dry-run", action="store_true", help="Score + report, never write")
    ap.add_argument("--repeat", type=int, default=1, help="Persona runs per eval (variance)")
    ap.add_argument("--show", action="store_true", help="Print the active template and exit")
    ap.add_argument("--revert", action="store_true", help="Drop override, restore default")
    args = ap.parse_args()

    if args.show:
        print(f"Active prompt: {'OVERRIDE' if prompt_store.is_override_active() else 'default'}\n")
        print(prompt_store.load_template())
        return 0
    if args.revert:
        print("Reverted to default prompt." if prompt_store.revert() else "No override to revert.")
        return 0
    return run(dry_run=args.dry_run, repeat=args.repeat)


if __name__ == "__main__":
    raise SystemExit(main())
