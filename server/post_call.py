"""Post-call finalization: persist the call record + ship it to Cekura.

Called once per call (idempotent per ``call_id``) from the bot when a call
ends — either gracefully via the ``end_call`` tool or on an abrupt
``on_client_disconnected``. It:

1. Assembles a structured call record (transcript, per-turn latency, load id,
   call sid, end reason, final scenario state).
2. Persists it locally under ``server/.call_logs/`` — ``<call_id>.json`` plus an
   appended line in ``index.jsonl``. This local log is what the offline
   self-improve / eval tooling reads, and it means the demo works with zero
   external dependencies.
3. Ships the transcript + latency to Cekura observability (no-op if Cekura is
   not configured).

All steps are best-effort and never raise into the pipeline teardown path.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from loguru import logger

import cekura_client

CALL_LOGS_DIR = Path(__file__).parent / ".call_logs"
_INDEX = CALL_LOGS_DIR / "index.jsonl"


def transcript_from_context(messages: list[dict], *, drop_first_user: bool = True) -> list[dict]:
    """Build a Cekura ``custom`` transcript from LLMContext messages.

    Keeps only spoken user/assistant turns. Drops the system/bootstrap greeting
    (the first synthetic "You are FreightVoice and you just dialed…" user
    message), tool-result messages, and assistant messages that are pure
    tool-calls with no spoken content (these are actions, not speech). Tool calls
    are surfaced compactly as ``[action: <tool>]`` so evaluators can still see
    that the agent acted.
    """
    out: list[dict] = []
    seen_first_user = False
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "user":
            if drop_first_user and not seen_first_user:
                seen_first_user = True
                continue  # synthetic call-open instruction, not a real driver turn
            seen_first_user = True
            if isinstance(content, str) and content.strip():
                out.append({"role": "user", "content": content.strip()})

        elif role == "assistant":
            if isinstance(content, str) and content.strip():
                out.append({"role": "assistant", "content": content.strip()})
            else:
                tool_calls = msg.get("tool_calls") or []
                names = [
                    tc.get("function", {}).get("name")
                    for tc in tool_calls
                    if tc.get("function", {}).get("name")
                ]
                if names:
                    out.append(
                        {"role": "assistant", "content": f"[action: {', '.join(names)}]"}
                    )
        # role == "tool" (results) and "system" are intentionally skipped.
    return out

async def _trigger_cekura_improve() -> None:
    """Background: ask Cekura to improve the carrier prompt from recent calls.

    Runs the sync improve_prompt_from_calls in a thread (it can take up to 3 min),
    then validates and saves the result so the next call uses the improved prompt.
    No-op if Cekura is not configured or the improved prompt fails validation.
    """
    if not cekura_client.is_configured() or not cekura_client.agent_id():
        return

    import prompt_store

    current = prompt_store.load_template()
    try:
        result = await asyncio.to_thread(
            cekura_client.improve_prompt_from_calls,
            prompt=current,
            call_logs=5,
        )
    except Exception as exc:
        logger.warning(f"Cekura self-improve: improve_prompt request failed: {exc}")
        return

    improved = (
        result.get("improved_prompt")
        or result.get("prompt")
        or result.get("suggested_prompt")
    )
    if not improved:
        logger.info("Cekura self-improve: no improved prompt in Cekura response")
        return

    ok, reason = prompt_store.validate(improved)
    if not ok:
        logger.warning(f"Cekura self-improve: candidate invalid ({reason}) — discarding")
        return

    saved, why = prompt_store.save_template(improved)
    if saved:
        logger.info("Cekura self-improve: applied improved prompt (active on next call)")
    else:
        logger.warning(f"Cekura self-improve: could not save improved prompt: {why}")


# Guards against double-finalize (end_call tool AND on_client_disconnected both
# firing for the same call). Process-local; fine for a single bot worker.
_finalized: set[str] = set()


def _persist(record: dict) -> None:
    try:
        CALL_LOGS_DIR.mkdir(exist_ok=True)
        call_id = record["call_id"]
        (CALL_LOGS_DIR / f"{call_id}.json").write_text(
            json.dumps(record, indent=2, default=str)
        )
        with _INDEX.open("a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        logger.info(f"Saved call record {call_id} -> {CALL_LOGS_DIR}")
    except Exception as exc:
        logger.warning(f"Could not persist call record: {exc}")


async def finalize_call(
    *,
    messages: list[dict],
    recorder_snapshot: dict,
    load_id: str | None = None,
    call_sid: str | None = None,
    from_number: str | None = None,
    ended_reason: str = "completed",
    scenario_state: dict | None = None,
    recording_url: str | None = None,
) -> dict | None:
    """Finalize one call. Returns the persisted record, or None if duplicate.

    Args:
        messages: ``LLMContext.get_messages()`` — used to build the transcript.
        recorder_snapshot: dict from ``CallRecorder.snapshot()`` (latency + duration).
    """
    call_id = call_sid or f"local-{int(time.time())}"
    if call_id in _finalized:
        logger.debug(f"finalize_call: {call_id} already finalized — skipping")
        return None
    _finalized.add(call_id)

    transcript = transcript_from_context(messages or [])
    latency = recorder_snapshot.get("latency", {})

    record = {
        "call_id": call_id,
        "load_id": load_id,
        "from_number": from_number,
        "ended_reason": ended_reason,
        "completed_at": datetime.now().isoformat(),
        "duration_secs": recorder_snapshot.get("duration_secs"),
        "num_turns": len(transcript),
        "transcript_json": transcript,
        "latency": latency,
        "scenario_state": scenario_state or {},
    }

    _persist(record)

    # Ship to Cekura observability (no-op if unconfigured). Pass load/latency as
    # metadata so Cekura's dashboards can slice by load and track latency drift.
    metadata = {
        "load_id": load_id,
        "ended_reason": ended_reason,
        "duration_secs": record["duration_secs"],
        "llm_ttfb_mean_ms": latency.get("llm_ttfb_mean_ms"),
        "stt_ttfb_mean_ms": latency.get("stt_ttfb_mean_ms"),
        "tts_ttfb_mean_ms": latency.get("tts_ttfb_mean_ms"),
        **(scenario_state or {}),
    }
    if transcript:
        await cekura_client.aobserve_call(
            transcript_json=transcript,
            call_id=call_id,
            call_ended_reason=ended_reason,
            voice_recording_url=recording_url,
            metadata=metadata,
        )
        # Kick off self-improvement in background — non-blocking, safe to ignore.
        asyncio.create_task(_trigger_cekura_improve())
    else:
        logger.info(f"finalize_call: {call_id} had no transcript turns — skipping Cekura observe")

    return record
