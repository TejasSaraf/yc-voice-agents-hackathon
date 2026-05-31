# FreightVoice 🚛📞

**AI voice agents that place outbound calls to freight carriers so a factory's production line never stops.**

---

## 1. What is this?

When a manufacturer is waiting on an outbound part, a logistics coordinator spends the day on the phone — dialing carriers, asking "where's my truck," and praying the line doesn't go down (a stalled assembly line costs up to **$1.8M/hour**). That's ~80 manual calls a day, and the signal that matters — *"this load is going to be late"* — almost always arrives too late to act on.

**FreightVoice** automates those calls. For every inbound load, an AI voice agent **calls the driver**, and in natural conversation:

1. Confirms **ETA + current location**, and reads the driver's **tone** (confident / calm / uncertain / frustrated).
2. Verifies the **cargo condition** (sealed, temperature-controlled).
3. **Assigns a dock + gate** and preps receiving.
4. Runs a **predictive risk model** on the load.
5. **Escalates to the logistics team** with a recommended action — *only* when the line is genuinely at risk.

The coordinator stops dialing and just watches a dashboard, handling exceptions. "Inbound logistics" = the freight coming *into* the plant; the **calls are outbound** (the agent dials the carrier).

**Pipeline:** Twilio ☎️ → Pipecat → Gradium STT → **NVIDIA Nemotron-3-Super-120B** (vLLM) → Gradium TTS.

---

## 2. Demo video (< 60s)

**▶ [Watch the demo (under 60 seconds)](ADD_YOUR_LINK_HERE)**

It's a live call, not a feature tour: we trigger a call from the dashboard, the agent talks a stressed, running-late driver through ETA → cargo → dock, scores the load as **at-risk**, and escalates to logistics — all watchable on the dashboard in real time.

---

## 3. How we used Cekura, Nemotron, and Pipecat

### NVIDIA Nemotron (open-weights model) — the agent's brain
`nemotron-3-super` (120B) served via vLLM's OpenAI-compatible API drives the entire conversation **and** the tool-calling. It decides what to say, classifies the driver's sentiment, converts fuzzy speech ("about 30 out, maybe more") into a minute count, and calls our six tools (`confirm_eta`, `verify_cargo_condition`, `assign_dock`, `assess_risk`, `alert_logistics_team`, `end_call`) in sequence. We run it as a **reasoning model with thinking ON** so its chain-of-thought streams in the hidden `reasoning_content` channel and never reaches the caller's ear.

### Pipecat — the real-time voice orchestration
Pipecat wires the telephony pipeline (Twilio WebSocket → STT → LLM → TTS → back) and the turn-taking. The hard part of voice isn't the prompt — it's **knowing when the human stopped talking** over compressed 8 kHz phone audio. We tuned: `MinWordsUserTurnStartStrategy` (start a turn on transcribed *words*, not raw VAD blips) + `SpeechTimeoutUserTurnStopStrategy` + `AlwaysUserMuteStrategy` (mute the mic while the bot speaks, to kill speakerphone echo that was self-interrupting the agent). A tail `CallRecorder` collects per-service TTFB latency.

### Cekura — testing, evaluation, and self-improvement
**Goal:** close the loop — observe every real call, evaluate it, and turn failures into prompt improvements without regressing.

- **Observability:** every completed call ships its transcript + per-turn latency to Cekura (`/observability/v1/observe/`), which runs its judges. This worked smoothly once we found the right `transcript_type`.
- **Self-improvement:** we built a **gated** loop (`auto_improve.py`): summarize issues from recent calls → ask the model to rewrite the prompt → **score the candidate against the current prompt on a regression suite** → apply the new prompt *only if it strictly wins with no per-persona regression*. The live bot picks up a promoted prompt on its next call, no restart.

**How much did we improve performance?** Our offline regression suite (`eval_agent.py`, 3 driver personas driving the real Nemotron model) sits at **3/3 pass** — sentiment classification, full tool sequence, correct escalation, and clean call completion. The gated loop's job is to *protect* that score: in testing it correctly **rejected** same-scoring rewrites (no needless drift) and surfaced a real regression — a call that didn't end cleanly because of a hallucinated tool argument (see feedback). We couldn't run Cekura's hosted `improve_prompt` rewriter end-to-end (server-side 500 — see feedback), so the applied improvement loop is the local eval-gated one.

---

## 4. What we built **during** the hackathon

**Borrowed (the starting point):** the *Field & Flower* voice-agent hackathon starter — the Pipecat ↔ Twilio transport plumbing and the Nemotron/Gradium service wrappers (`nemotron_llm.py`, `nvidia_stt.py`).

**New, built today** — essentially the entire product:

- **The FreightVoice domain & agent** — carrier check-in + supplier-compliance scenarios, the six-tool call procedure, and the system prompt (`freight_scenarios.py`).
- **Predictive risk model** (`risk_scorer.py`) — a weighted score (sentiment 0.30, historical OTD 0.20, time-pressure 0.20, weather 0.15, ETA-vagueness 0.15) through a sigmoid → 0–100 + Monitor/Warning/Critical, with **live NOAA weather** lookups per lane.
- **Outbound orchestration** (`outbound.py`, `api_server.py`) — dashboard / risk-threshold / external-signal / missed-milestone triggers, plus per-call load routing.
- **Operations dashboard + YC-style landing page** (`frontend/`) — a monochrome enterprise data-grid of inbound loads and **call records**, each scored, with live call status and a per-call eval breakdown.
- **The evaluation + self-improvement stack** — per-call local scoring (`call_eval.py`), the offline persona regression harness (`eval_agent.py`), Cekura observability + prompt-improvement wiring (`cekura_client.py`, `self_improve.py`), and the **gated prompt self-improvement loop** (`auto_improve.py` + `prompt_store.py`).
- **Reliability fixes from real calls** — graceful call finalization on every end path, JSON-safe call records, and tolerance for hallucinated tool arguments.

---

## 5. Feedback on the tools

### NVIDIA Nemotron
**Did well:**
- **Tool-calling is strong** — it reliably ran our six-step procedure in order and rarely skipped a step.
- **Sentiment reading is genuinely good** — it nailed "uncertain" vs "frustrated" from messy, real phone transcripts, which is the highest-weighted signal in our risk model.
- Thinking-in-a-separate-channel is exactly right for voice.

**Could be better:**
- **Hallucinated tool arguments.** On a live call it invoked `end_call(call_id="call_123")` — a parameter that doesn't exist — which threw and left **dead air** until the human hung up. We had to make tools tolerate unexpected kwargs. Tighter adherence to the provided tool schema (no invented args) matters a lot for voice, where a thrown tool = silence on the line.
- **TTFB while thinking** is ~2–5s to the first answer token; noticeable on a phone call. A faster "reason briefly, answer now" mode for latency-sensitive turns would help.

### Cekura (self-improvement loops) — including bugs
**What worked:** observability ingestion was smooth once we found the right format.

**Bugs / friction we hit:**
1. **`transcript_type: "custom"` 400s** — the expected value is rejected (`"custom" is not a valid choice`). The value that actually works is **`"pipecat"`** for a plain `{role, content}` transcript. This cost us real time.
2. **`improve_prompt` returns a generic 500** for a well-formed request when the agent has **no evaluation metrics configured**. It validated our payload (`agent_id` + integer `call_logs` + `prompt`) and then 500'd with *"Something went wrong, please try again."* It should fail with a clear 4xx (e.g. *"no metrics configured for this agent"*) instead of a 500 — we burned time assuming our request was malformed.
3. **Inconsistent field names** — `observe` wants `agent`, but `improve_prompt` wants `agent_id` (and `agent` is silently ignored). `call_logs` needs an integer or ID list (not `"all"`, which is "deprecated"), and it caps silently at the number available. A consistent schema + clearer errors would make wiring the self-improvement loop much faster.

**Net:** the *concept* (observe → judge → improve_prompt) is exactly the loop we wanted; the hosted rewriter just wasn't reachable for an agent without preconfigured metrics, so we built a local eval-gated version to demonstrate the loop safely.

### Pipecat / Gradium / Twilio
- **Pipecat** turn-taking strategies are powerful but under-documented for **telephony** specifically — SmartTurn returned `NOT_COMPLETE` on 8 kHz audio and stalled turns for ~15s; we only got reliable behavior after combining MinWords + SpeechTimeout + AlwaysUserMute. A "phone preset" would save everyone this.
- **Direct functions** crash the pipeline on an unexpected kwarg from the LLM; gracefully dropping unknown args (or surfacing a tool error back to the model instead of an exception) would be safer for voice.
- **Gradium** STT/TTS latency was excellent (sub-200ms TTS TTFB) and was our reliable fallback when the shared ASR endpoint stalled under load.

---

## 6. Try it

**Run locally:**
```bash
# Backend (FastAPI dashboard API + outbound orchestrator)
cd server && uv run uvicorn api_server:app --reload --port 8000
# Voice bot (Pipecat)
uv run bot-freightvoice.py
# Frontend (dashboard + landing page)
cd ../frontend && npm install && npm run dev   # http://localhost:5173
```

**Evaluation & self-improvement:**
```bash
cd server
uv run eval_agent.py        # offline regression: 3 driver personas vs the real model
uv run self_improve.py      # observe-driven analysis (Cekura, or local fallback)
uv run auto_improve.py      # gated prompt self-improvement (apply only if it beats current)
```
