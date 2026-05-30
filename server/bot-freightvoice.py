"""FreightVoice — shipper-side inbound-coordination voice agent (Version 2: Nemotron).

FreightVoice calls carriers and suppliers on a manufacturer's behalf so the
logistics team goes from 80 manual calls a day to reviewing a dashboard and
handling only genuine exceptions. It solves three shipper-side problems:

  1. Inbound parts coordination  — confirm ETA + dock, prep receiving, verify
                                    shipper-specific cargo condition.
  2. Production-line protection   — score delivery risk on every inbound load
                                    and alert logistics BEFORE the line stops.
  3. Supplier compliance calls    — multilingual outreach to confirm pricing,
                                    lead times, and compliance docs when tariffs
                                    or routing change.

Pick the scenario with the FREIGHTVOICE_SCENARIO env var:

    FREIGHTVOICE_SCENARIO=carrier      # Problems 1 & 2 (default)
    FREIGHTVOICE_SCENARIO=compliance   # Problem 3

Optionally pin which load/supplier the demo call is about:

    FREIGHTVOICE_LOAD_ID=TSLA-BAT-0412
    FREIGHTVOICE_SUPPLIER_ID=APPL-CAM-221

Pipeline: Nemotron Speech Streaming STT → Nemotron-3-Super-120B LLM → Gradium TTS.

Run the bot using::

    uv run bot-freightvoice.py
"""

import os

import aiohttp
from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from call_recorder import CallRecorder
from post_call import finalize_call
from think_filter import ThinkTagFilter
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import (
    RunnerArguments,
    SmallWebRTCRunnerArguments,
    WebSocketRunnerArguments,
)
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.gradium.stt import GradiumSTTService
from pipecat.services.gradium.tts import GradiumTTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
    MinWordsUserTurnStartStrategy,
)
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from freight_scenarios import build_scenario, get_opening_line
from nemotron_llm import VLLMOpenAILLMService
from nvidia_stt import NVidiaWebSocketSTTService

load_dotenv(override=True)


async def get_call_info(call_sid: str) -> dict:
    """Fetch call information from Twilio REST API using aiohttp.

    Args:
        call_sid: The Twilio call SID

    Returns:
        Dictionary containing call information including from_number, to_number, status, etc.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        logger.warning("Missing Twilio credentials, cannot fetch call info")
        return {}

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json"

    try:
        auth = aiohttp.BasicAuth(account_sid, auth_token)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=auth) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Twilio API error ({response.status}): {error_text}")
                    return {}
                data = await response.json()
                return {
                    "from_number": data.get("from"),
                    "to_number": data.get("to"),
                }
    except Exception as e:
        logger.error(f"Error fetching call info from Twilio: {e}")
        return {}


async def run_bot(
    transport: BaseTransport,
    from_number: str | None = None,
    call_sid: str | None = None,
    audio_in_sample_rate: int = 16000,
    audio_out_sample_rate: int = 24000,
    scenario_name: str | None = None,
    load_id_override: str | None = None,
    supplier_id_override: str | None = None,
):
    """Main bot logic.

    ``scenario_name`` / ``load_id_override`` / ``supplier_id_override`` come from
    the per-call WebSocket body (a dashboard-triggered call names its own load).
    They take precedence over the FREIGHTVOICE_* env defaults so each call is
    about the load that was actually dialed — not always the .env-pinned one.
    """
    logger.info("Starting FreightVoice bot")

    tool_functions, system_instruction, greeting = build_scenario(
        scenario=scenario_name,
        load_id=load_id_override,
        supplier_id=supplier_id_override,
    )
    tools = ToolsSchema(standard_tools=tool_functions)
    load_id = (load_id_override or os.getenv("FREIGHTVOICE_LOAD_ID", "TSLA-BAT-0412")).upper()

    # Speech-to-Text — Gradium (dedicated, low-latency). The shared NVIDIA ASR
    # endpoint stalls under hackathon load (18s TTFB observed). Brain stays
    # Nemotron — only the ears swap to a dedicated provider.
    #
    # To switch back to NVIDIA ASR once the shared endpoint is healthy, set
    # USE_NVIDIA_STT=true in .env.
    if os.getenv("USE_NVIDIA_STT", "false").lower() == "true":
        stt = NVidiaWebSocketSTTService(
            url=os.getenv("NVIDIA_ASR_URL", "ws://192.168.7.228:8081"),
            strip_interim_prefix=True,
        )
        logger.info("STT: NVIDIA Nemotron Speech Streaming (shared endpoint)")
    else:
        stt = GradiumSTTService(
            api_key=os.environ["GRADIUM_API_KEY"],
            settings=GradiumSTTService.Settings(language=Language.EN),
        )
        logger.info("STT: Gradium (dedicated, NVIDIA ASR fallback path)")

    # LLM — Nemotron-3-Super-120B via vLLM (OpenAI-compatible /v1).
    #
    # Thinking is ON by default. Nemotron-3-Super is a REASONING model: it always
    # reasons before answering. With thinking ENABLED the reasoning streams in the
    # separate `reasoning_content` channel, which pipecat does NOT send to TTS —
    # so only the final spoken answer reaches the driver. With thinking DISABLED
    # the model dumps that same reasoning into the regular `content` channel and
    # the bot literally SPEAKS its chain-of-thought out loud ("The driver says…",
    # "I'll record this in confirm_eta", "Let me call confirm_eta"). Keep it on.
    #
    # Trade-off: ~1-2s extra TTFB while it thinks (nemotron_llm.py defers the TTFB
    # metric to the first real answer token to measure this honestly).
    enable_thinking = os.getenv("NEMOTRON_ENABLE_THINKING", "true").lower() == "true"
    llm = VLLMOpenAILLMService(
        api_key=os.getenv("NEMOTRON_LLM_API_KEY", "EMPTY"),
        base_url=os.getenv("NEMOTRON_LLM_URL", "http://192.168.7.228:8000/v1"),
        settings=VLLMOpenAILLMService.Settings(
            model=os.getenv("NEMOTRON_LLM_MODEL", "nvidia/nemotron-3-super"),
            system_instruction=system_instruction,
            extra={"extra_body": {"chat_template_kwargs": {"enable_thinking": enable_thinking}}},
        ),
    )

    # Text-to-Speech — Gradium.
    tts = GradiumTTSService(
        api_key=os.environ["GRADIUM_API_KEY"],
        settings=GradiumTTSService.Settings(
            voice=os.getenv("GRADIUM_VOICE_ID", "Eu9iL_CYe8N-Gkx_"),
        ),
    )

    for fn in tool_functions:
        llm.register_direct_function(fn)

    context = LLMContext(tools=tools)

    # VAD tuned for 8kHz telephony audio (Twilio μ-law upsampled to 16kHz).
    #
    # Echo is NOT handled here anymore — AlwaysUserMuteStrategy (below) mutes
    # the mic entirely while the bot speaks, so we no longer need ultra-strict
    # VAD to reject the bot's own echo. An earlier attempt at confidence=0.85 /
    # stop_secs=0.8 backfired: it was so strict that REAL phone speech never
    # cleared the bar, so VAD never fired, the SpeechTimeout stop strategy never
    # got a VAD-stop event, and turns hung for ~15s before timing out.
    #
    # These values are slightly more sensitive than the library defaults
    # (confidence 0.7, min_volume 0.6) because compressed phone audio is quieter
    # than studio mic input. stop_secs is kept at 0.2 — the value
    # SpeechTimeoutUserTurnStopStrategy's built-in STT p99 latency assumes
    # (VAD_STOP_SECS); raising it collapses the STT safety-net wait.
    phone_vad = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.6,
            min_volume=0.5,
            start_secs=0.2,
            stop_secs=0.2,
        )
    )

    # Turn strategies for phone calls.
    #
    # SmartTurn (TurnAnalyzerUserTurnStopStrategy) does NOT work reliably here:
    #   - stop_secs=0.8 > GRADIUM_TTFS_P99=0.6 collapses the STT wait to 0s
    #   - 8kHz phone audio (upsampled to 16kHz) causes SmartTurn to return
    #     NOT_COMPLETE, so _turn_complete=False and the turn never fires
    #   - Fallback: the controller's 5s timeout fires with strategy=None,
    #     producing 5+ seconds of dead silence on the call
    #
    # Fix: SpeechTimeoutUserTurnStopStrategy — VAD + fixed silence window,
    # no AI turn model. After VAD stops, wait 0.3s for the user to resume,
    # then fire as soon as a transcription arrives.
    #
    # Echo control — AlwaysUserMuteStrategy mutes user input WHILE THE BOT IS
    # SPEAKING. On a speakerphone the bot's own TTS plays out the phone speaker
    # and bleeds back into the mic; Gradium STT then transcribes it, which fires
    # TranscriptionUserTurnStartStrategy (independent of VAD) and interrupts the
    # bot mid-sentence — the "voice breaking" + "client stopped speaking even
    # when I said nothing" symptom. Muting during bot speech stops the echo from
    # ever reaching STT. Trade-off: no barge-in while the bot talks — acceptable
    # for this short, dispatcher-led call flow.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=phone_vad,
            user_turn_strategies=UserTurnStrategies(
                # START on transcribed WORDS, not raw VAD. The default start set
                # includes VADUserTurnStartStrategy, which broadcasts an
                # interruption the instant Silero VAD thinks it hears speech —
                # even line noise / a breath with no words. With thinking ON the
                # LLM spends ~2s reasoning before the bot speaks; a phantom VAD
                # blip in that window was broadcasting an interruption that
                # CANCELLED the in-flight response, so the bot went silent and
                # never recovered (logs: VADUserStartedSpeakingFrame with no
                # following transcription, then every later turn fires with
                # strategy=None). MinWords only starts a turn once real words are
                # transcribed (1 word when the bot is idle/thinking, min_words
                # while the bot speaks), so noise can no longer kill a response.
                start=[MinWordsUserTurnStartStrategy(min_words=3)],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.3)],
            ),
            user_mute_strategies=[AlwaysUserMuteStrategy()],
        ),
    )

    # Records per-service TTFB latency (MetricsFrames reach the tail). The
    # transcript is read from `context` at end-of-call, not from this processor.
    call_recorder = CallRecorder()

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            ThinkTagFilter(),  # drop any <think>…</think> before it reaches TTS
            tts,
            transport.output(),
            assistant_aggregator,
            call_recorder,  # tail: observe MetricsFrames for latency
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=audio_in_sample_rate,
            audio_out_sample_rate=audio_out_sample_rate,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        # Latency win: the opening line is a deterministic dispatcher script, so
        # speak it IMMEDIATELY via TTS instead of paying ~2s for the LLM to
        # generate the first turn while the driver waits in silence. We seed the
        # same line into the context as the assistant's opening so the model has
        # correct continuity for the rest of the call, and we DON'T queue an
        # LLMRunFrame. Set FREIGHTVOICE_INSTANT_GREETING=false to fall back to
        # the LLM-generated opening.
        opening = get_opening_line()
        instant = os.getenv("FREIGHTVOICE_INSTANT_GREETING", "true").lower() == "true"
        if opening and instant:
            context.add_message({"role": "assistant", "content": opening})
            await worker.queue_frames([TTSSpeakFrame(opening)])
        else:
            context.add_message({"role": "user", "content": greeting})
            await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        # Finalize BEFORE cancelling the worker: capture the transcript from the
        # LLM context + latency from the recorder, persist locally, and ship to
        # Cekura. finalize_call is idempotent per call_sid, so this is safe even
        # if the graceful end_call path also fires.
        try:
            from freight_scenarios import get_last_call_state

            await finalize_call(
                messages=context.get_messages(),
                recorder_snapshot=call_recorder.snapshot(),
                load_id=load_id,
                call_sid=call_sid,
                from_number=from_number,
                ended_reason="disconnected",
                scenario_state=get_last_call_state(),
            )
        except Exception as exc:
            logger.warning(f"Post-call finalize failed: {exc}")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()

    try:
        from freight_scenarios import get_last_call_state

        await finalize_call(
            messages=context.get_messages(),
            recorder_snapshot=call_recorder.snapshot(),
            load_id=load_id,
            call_sid=call_sid,
            from_number=from_number,
            ended_reason="completed",
            scenario_state=get_last_call_state(),
        )
    except Exception as exc:
        logger.warning(f"Post-call finalize failed: {exc}")


async def bot(runner_args: RunnerArguments):
    """Main bot entry point."""

    from_number: str | None = None
    call_sid: str | None = None
    transport_overrides: dict = {}
    scenario_name: str | None = None
    load_id_override: str | None = None
    supplier_id_override: str | None = None

    if os.environ.get("ENV") != "local":
        from pipecat.audio.filters.krisp_viva_filter import KrispVivaFilter

        krisp_filter = KrispVivaFilter()
    else:
        krisp_filter = None

    match runner_args:
        case SmallWebRTCRunnerArguments():
            webrtc_connection: SmallWebRTCConnection = runner_args.webrtc_connection
            transport = SmallWebRTCTransport(
                webrtc_connection=webrtc_connection,
                params=TransportParams(
                    audio_in_enabled=True,
                    audio_in_filter=krisp_filter,
                    audio_out_enabled=True,
                ),
            )
        case WebSocketRunnerArguments():
            transport_overrides["audio_in_sample_rate"] = 8000
            transport_overrides["audio_out_sample_rate"] = 8000

            _, call_data = await parse_telephony_websocket(runner_args.websocket)
            call_sid = call_data["call_id"]
            body = call_data.get("body") or {}
            load_id_override = body.get("load") or body.get("FREIGHTVOICE_LOAD_ID")
            scenario_name = body.get("scenario") or body.get("FREIGHTVOICE_SCENARIO")
            supplier_id_override = body.get("supplier") or body.get("FREIGHTVOICE_SUPPLIER_ID")
            if load_id_override or scenario_name:
                logger.info(
                    f"Per-call context from body: scenario={scenario_name} "
                    f"load={load_id_override} supplier={supplier_id_override}"
                )
            call_info = await get_call_info(call_data["call_id"])
            if call_info:
                from_number = call_info.get("from_number")
                logger.info(f"Call from: {from_number} to: {call_info.get('to_number')}")

            serializer = TwilioFrameSerializer(
                stream_sid=call_data["stream_id"],
                call_sid=call_data["call_id"],
                account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            )

            transport = FastAPIWebsocketTransport(
                websocket=runner_args.websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_in_filter=krisp_filter,
                    audio_out_enabled=True,
                    add_wav_header=False,
                    serializer=serializer,
                ),
            )
        case _:
            logger.error(f"Unsupported runner arguments type: {type(runner_args)}")
            return

    await run_bot(
        transport,
        from_number=from_number,
        call_sid=call_sid,
        scenario_name=scenario_name,
        load_id_override=load_id_override,
        supplier_id_override=supplier_id_override,
        **transport_overrides,
    )


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
