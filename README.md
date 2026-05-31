# FreightVoice

**An AI voice agent that calls freight brokers on behalf of shippers — so manufacturers stop spending their day chasing load status updates.**

---

## 1. What is this?

In freight, a **shipper** (like a manufacturer) hires a **freight broker** to find and coordinate carriers. The shipper's logistics team then spends all day calling that broker — asking "where's my truck, is it going to be late, what's the status?" A stalled assembly line costs up to **$1.8M per hour**, and the warning that a load is running late almost always arrives too late to do anything about it.

We're solving the **shipper side** of that relationship. FreightVoice is the tool the shipper's team uses — our AI agent makes those status calls **on the shipper's behalf**, dialing the freight broker (or carrier) so no human has to. In a natural phone conversation, it:

1. Gets the current location and ETA — and picks up on whether the driver sounds confident or stressed
2. Checks that the cargo is sealed and in good condition
3. Assigns a dock and gate so receiving is ready
4. Runs a quick risk score on that load
5. Alerts the logistics team only when something actually needs human attention

The person managing logistics stops making calls and just watches a dashboard, stepping in for real exceptions. **All calls are outbound — the agent dials out.**

**How it works under the hood:** Twilio handles the phone connection → Pipecat manages the voice pipeline → Gradium transcribes speech → NVIDIA Nemotron-3-Super-120B runs the conversation and decides what to do → Gradium converts the response back to speech.

---

## 2. Demo video (under 60 seconds)

**[Watch the demo](https://youtube.com/shorts/b9T2XrsBO7M?si=wIV5iGA5S-mpny5J)**

The demo shows a live call: we trigger it from the dashboard, the agent talks to a driver who's running behind, gets the ETA and cargo status, scores the load as at-risk, and escalates to logistics — all visible on the dashboard in real time.

---

## 3. How we used Cekura, Nemotron, and Pipecat

### NVIDIA Nemotron — the agent's brain

We used `nemotron-3-super` (120B), an open-weights model, served via a vLLM endpoint with an OpenAI-compatible API. It drives the entire conversation: deciding what to say, reading the driver's tone, turning vague answers like "about 30 out, maybe more" into a concrete ETA, and calling six tools in sequence (`confirm_eta`, `verify_cargo_condition`, `assign_dock`, `assess_risk`, `alert_logistics_team`, `end_call`).

We ran it in reasoning mode, so the model's chain of thought stays hidden and never gets read aloud to the driver.

### Pipecat — real-time voice orchestration

Pipecat connects everything: the Twilio phone line → speech-to-text → the language model → text-to-speech → back to the caller. The trickiest part of phone calls isn't the AI — it's knowing when someone has actually finished talking on compressed, low-quality audio.

We tuned three settings to get reliable turn-taking: start a response only after real transcribed words (not noise), use a speech timeout to detect when the driver stopped talking, and mute the mic while the agent speaks to stop the agent from interrupting itself through speakerphone echo.

### Cekura — testing and self-improvement

**What we were trying to do:** after each real call, automatically check whether the agent did its job, and use those results to improve the prompt — without breaking what was already working.

We built a gated improvement loop:
1. Every completed call sends its transcript and timing data to Cekura, which runs its evaluation judges
2. We use those results (plus a local fallback when Cekura's hosted rewriter wasn't reachable) to generate a candidate updated prompt
3. Before applying it, we run the candidate against an offline regression suite — three driver personas tested against the real Nemotron model
4. We only swap in the new prompt if it strictly improves things with no regressions

**Results:** our offline suite runs at 3/3 pass — correct sentiment classification, full tool sequence, proper escalation, and clean call ending. The gated loop correctly rejected same-scoring rewrites (avoiding meaningless drift) and caught a real regression where the agent didn't end the call cleanly due to a bad tool argument.

---

## 4. What we built during the hackathon

**What we started with:** the Field & Flower voice-agent starter — the Twilio/Pipecat plumbing and service wrappers for Nemotron and Gradium.

**What we built new during the hackathon:**

- **The FreightVoice agent** — the carrier check-in scenario, the six-step call procedure, and the system prompt
- **Risk scoring** (`risk_scorer.py`) — a weighted score combining driver sentiment, historical on-time delivery, time pressure, weather, and ETA confidence, with live NOAA weather lookups per shipping lane
- **Outbound call orchestration** (`outbound.py`, `api_server.py`) — triggering calls based on risk thresholds, missed milestones, or manual dispatch
- **Operations dashboard and landing page** (`frontend/`) — a live view of all loads and call records, each with a risk score and call evaluation breakdown
- **The evaluation and self-improvement stack** — per-call scoring, an offline persona regression harness, Cekura integration, and the gated prompt improvement loop
- **Reliability fixes from real calls** — handling calls that end unexpectedly, tolerating when the model invents tool arguments, and keeping call records JSON-safe

---

## 5. Feedback on the tools

### NVIDIA Nemotron

**What it did well:**
- Tool calling is solid — it reliably ran our six-step procedure in order and rarely skipped a step
- Sentiment reading is genuinely good — it correctly classified driver tone from real, messy phone transcripts, which is the most important signal in our risk model
- Keeping reasoning in a separate channel so it never reaches the caller is exactly the right design for voice

**Where it could improve:**
- **It invents tool arguments.** On a live call it called `end_call(call_id="call_123")` — a parameter we never defined. That threw an error and left dead air on the line until the driver hung up. We had to patch our tools to silently ignore unexpected arguments. For voice, a failed tool call means silence, which is bad — tighter adherence to the schema would help a lot.
- **First-response latency while thinking** is 2–5 seconds. That's noticeable on a phone call. A mode that reasons briefly but responds faster would make it more natural for real-time conversations.

### Cekura

**What worked:** once we found the right format, sending transcripts and getting evaluations back was smooth.

**Bugs and friction we hit:**

1. **Wrong `transcript_type` value in the docs.** We tried `"custom"` as documented and got a 400 error. The value that actually works is `"pipecat"` for a plain `{role, content}` transcript. Cost us real time tracking this down.

2. **`improve_prompt` returns a 500 with no explanation** when the agent has no evaluation metrics configured. It accepted our request, then returned a generic "Something went wrong, please try again." It should return a clear 4xx error like "no metrics configured for this agent" — we assumed our request was malformed and spent a long time debugging it.

3. **Inconsistent field names between endpoints.** The `observe` endpoint wants `agent`, but `improve_prompt` wants `agent_id` (and silently ignores `agent`). The `call_logs` field needs an ID or integer — passing `"all"` is deprecated and fails silently. A consistent schema and clearer error messages would make wiring the self-improvement loop much faster.

The core concept — observe every call, judge it, use that to improve the prompt — is exactly the loop we wanted to build. We just couldn't get the hosted rewriter to work end-to-end, so we built a local eval-gated version to demonstrate the same loop safely.

### Pipecat

- Turn-taking strategies are powerful but poorly documented for phone calls specifically. SmartTurn returned `NOT_COMPLETE` on 8 kHz audio and stalled turns for up to 15 seconds. We only got reliable behavior after combining MinWords + SpeechTimeout + AlwaysUserMute. A phone-call preset with these settings already configured would save a lot of time.
- When the language model invents a tool argument, it crashes the pipeline instead of surfacing the error back to the model. Graceful handling (drop the unknown arg or return a tool error) would be much safer for voice, where a crash means silence.

### Gradium (STT/TTS)

STT and TTS latency was excellent — sub-200ms TTS first-token — and was our reliable fallback when the shared ASR endpoint got slow under load.

---
