"""Cekura client — testing, observability, and self-improvement for FreightVoice.

Cekura (https://cekura.ai) is a QA + observability platform for voice agents.
This module wraps the three Cekura capabilities FreightVoice uses:

1. **Observability** — after every call we POST the transcript + per-turn latency
   to ``/observability/v1/observe/``. Cekura stores it as a CallLog and runs its
   voice-quality + agent-performance judges (sentiment, instruction adherence,
   tool-call correctness, latency, interruptions, gibberish, …).

2. **Self-improvement** — ``improve_prompt_from_calls()`` calls
   ``/observability/v1/call-logs/improve_prompt/``, which reads recent production
   call logs + their metric outcomes and proposes concrete system-prompt edits.
   This is the "self-improve after each call ends" loop.

3. **Test cases / regression** — ``run_scenarios()`` triggers Cekura evaluator
   scenarios (simulated driver personas) against the live agent and returns a
   result id you can poll for pass/fail.

Everything is **gated on configuration**: if ``CEKURA_API_KEY`` (and, where
needed, ``CEKURA_AGENT_ID``) is unset, calls become no-ops that log a hint
instead of raising — so the bot and dashboard run fine without a Cekura account.

Env:
    CEKURA_API_KEY    Organization API key (header: X-CEKURA-API-KEY)
    CEKURA_AGENT_ID   The agent id registered in Cekura (int or str)
    CEKURA_API_URL    Override base URL (default https://api.cekura.ai)
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from loguru import logger

DEFAULT_BASE_URL = "https://api.cekura.ai"


def _base_url() -> str:
    return os.getenv("CEKURA_API_URL", DEFAULT_BASE_URL).rstrip("/")


def api_key() -> str | None:
    """Return the configured Cekura API key, or None."""
    key = os.getenv("CEKURA_API_KEY", "").strip()
    return key or None


def agent_id() -> str | None:
    """Return the configured Cekura agent id, or None.

    Defensive: strips a trailing inline ``# comment`` (a common .env copy-paste
    artifact — python-dotenv can otherwise read the placeholder comment AS the
    value) and validates the id is a positive integer, since Cekura's endpoints
    400 on a non-integer agent. Returns None for anything that isn't a real id,
    so callers degrade to no-ops with a clear log instead of a cryptic 400.
    """
    raw = os.getenv("CEKURA_AGENT_ID", "")
    cleaned = raw.split("#", 1)[0].strip()
    if not cleaned:
        return None
    if not cleaned.isdigit():
        logger.warning(
            f"CEKURA_AGENT_ID={raw.strip()!r} is not a valid integer agent id — "
            "set it to the numeric id of an agent in your Cekura account "
            "(create one first; see cekura_client.list_agents). Skipping Cekura."
        )
        return None
    return cleaned


def is_configured() -> bool:
    """True when at least an API key is present."""
    return api_key() is not None


def _headers() -> dict[str, str]:
    return {"X-CEKURA-API-KEY": api_key() or "", "Content-Type": "application/json"}


# ── Observability ───────────────────────────────────────────────────────────


def build_observe_payload(
    *,
    transcript_json: list[dict],
    call_id: str,
    call_ended_reason: str | None = None,
    voice_recording_url: str | None = None,
    metadata: dict | None = None,
    dynamic_variables: dict | None = None,
) -> dict[str, Any]:
    """Assemble the ``/observability/v1/observe/`` request body.

    ``transcript_json`` is a list of ``{"role", "content"}`` turns (role in
    {"user", "assistant"}); sent under Cekura's ``transcript_type: "pipecat"``
    ingest schema.
    """
    payload: dict[str, Any] = {
        "agent": agent_id(),
        "transcript_type": "pipecat",
        "transcript_json": transcript_json,
        "call_id": call_id,
    }
    if call_ended_reason:
        payload["call_ended_reason"] = call_ended_reason
    if voice_recording_url:
        payload["voice_recording_url"] = voice_recording_url
    if metadata:
        payload["metadata"] = metadata
    if dynamic_variables:
        payload["dynamic_variables"] = dynamic_variables
    return payload


async def aobserve_call(
    *,
    transcript_json: list[dict],
    call_id: str,
    call_ended_reason: str | None = None,
    voice_recording_url: str | None = None,
    metadata: dict | None = None,
    dynamic_variables: dict | None = None,
    timeout: float = 8.0,
) -> dict | None:
    """Async: ingest one completed call into Cekura observability.

    Safe to fire-and-forget — never raises; returns the response JSON or None.
    """
    if not is_configured():
        logger.debug("Cekura not configured (CEKURA_API_KEY unset) — skipping observe")
        return None
    if not agent_id():
        logger.warning("CEKURA_AGENT_ID unset — cannot attribute call log; skipping observe")
        return None

    payload = build_observe_payload(
        transcript_json=transcript_json,
        call_id=call_id,
        call_ended_reason=call_ended_reason,
        voice_recording_url=voice_recording_url,
        metadata=metadata,
        dynamic_variables=dynamic_variables,
    )
    url = f"{_base_url()}/observability/v1/observe/"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=_headers(), json=payload)
        if resp.status_code >= 400:
            logger.warning(f"Cekura observe failed [{resp.status_code}]: {resp.text[:300]}")
            return None
        logger.info(f"Cekura: ingested call {call_id} ({len(transcript_json)} turns)")
        return resp.json() if resp.content else {"ok": True}
    except Exception as exc:
        logger.warning(f"Cekura observe error: {exc}")
        return None


# ── Self-improvement (prompt improvement from production call logs) ───────────


def improve_prompt_from_calls(
    *,
    prompt: str,
    call_logs: int = 10,
    extra: dict | None = None,
    timeout: float = 180.0,
    lookback_days: int | None = None,  # accepted for back-compat; endpoint ignores it
) -> dict:
    """Ask Cekura to propose prompt improvements from recent call logs.

    Sync (used by the offline self-improve script). Returns the raw JSON, which
    contains the proposed improved prompt and/or categorized failure issues.

    The endpoint requires:
      * ``agent_id`` — numeric agent id (NOT ``agent``)
      * ``call_logs`` — an INTEGER count of recent logs to reevaluate, capped at
        the number actually available (Cekura 400s with "Maximum length is N" if
        you ask for more, so we transparently retry at the cap)
      * ``prompt`` — the current system prompt to improve
    """
    if not is_configured():
        raise RuntimeError("CEKURA_API_KEY is not set")
    if not agent_id():
        raise RuntimeError("CEKURA_AGENT_ID is not set (or not a valid integer id)")

    def _post(n: int) -> httpx.Response:
        payload: dict[str, Any] = {
            "agent_id": agent_id(),
            "call_logs": n,
            "prompt": prompt,
        }
        if extra:
            payload.update(extra)
        url = f"{_base_url()}/observability/v1/call-logs/improve_prompt/"
        return httpx.post(url, headers=_headers(), json=payload, timeout=timeout)

    resp = _post(call_logs)
    if resp.status_code == 400 and "Maximum length is" in resp.text:
        import re

        m = re.search(r"Maximum length is (\d+)", resp.text)
        if m:
            resp = _post(int(m.group(1)))
    resp.raise_for_status()
    return resp.json()


# ── Test cases / regression scenarios ────────────────────────────────────────


def list_agents(timeout: float = 30.0) -> list[dict]:
    """List AI agents registered in Cekura (use to discover your agent id)."""
    if not is_configured():
        raise RuntimeError("CEKURA_API_KEY is not set")
    url = f"{_base_url()}/test_framework/v1/aiagents/"
    resp = httpx.get(url, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", data) if isinstance(data, dict) else data


def run_scenarios(
    scenario_ids: list[int],
    *,
    frequency: int = 1,
    mode: str = "voice",
    timeout: float = 60.0,
) -> dict:
    """Trigger Cekura evaluator scenarios (test cases) against the agent.

    Args:
        scenario_ids: Cekura scenario ids to run.
        frequency: how many times to run each scenario.
        mode: "voice" (outbound phone), "pipecat_v2" (Pipecat Cloud), etc.

    Returns the result object (poll its ``id`` for pass/fail).
    """
    if not is_configured():
        raise RuntimeError("CEKURA_API_KEY is not set")
    endpoint = {
        "voice": "run_scenarios_voice",
        "pipecat": "run_scenarios_pipecat",
        "pipecat_v2": "run_scenarios_pipecat_v2",
    }.get(mode, "run_scenarios_voice")
    url = f"{_base_url()}/test_framework/v1/scenarios/{endpoint}/"
    payload = {
        "scenarios": [{"scenario": sid} for sid in scenario_ids],
        "frequency": frequency,
    }
    resp = httpx.post(url, headers=_headers(), json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_result(result_id: int, timeout: float = 30.0) -> dict:
    """Fetch a scenario-run result by id (for polling pass/fail)."""
    if not is_configured():
        raise RuntimeError("CEKURA_API_KEY is not set")
    url = f"{_base_url()}/test_framework/v1/results/{result_id}/"
    resp = httpx.get(url, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    return resp.json()
