"""In-pipeline call recorder: per-turn latency for Cekura + the dashboard.

A single ``CallRecorder`` ``FrameProcessor`` dropped at the TAIL of the Pipecat
pipeline records latency from Pipecat ``MetricsFrame``s (enabled via
``PipelineParams(enable_metrics=True)``): TTFB samples per processor (STT, LLM,
TTS). We summarize mean / p50 / p90 per service so latency regressions are
visible per call and in aggregate.

Why latency-only (not transcript): the user aggregator *consumes*
``TranscriptionFrame``s and does not push them downstream, so a tail-placed
processor never sees user turns. The authoritative transcript is read instead
from the ``LLMContext`` at end-of-call (see ``post_call.transcript_from_context``),
which already holds both user and assistant messages. ``MetricsFrame``s, by
contrast, are forwarded all the way to the tail, so this is the right place to
collect them.

The recorder is a passthrough — it never modifies frames, only observes them.
Call ``snapshot()`` at end-of-call for the latency report + call duration.
"""

from __future__ import annotations

import time
from statistics import mean

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    MetricsFrame,
    StartFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


class CallRecorder(FrameProcessor):
    """Passthrough processor that records per-service TTFB latency + duration."""

    def __init__(self):
        super().__init__()
        self._t0: float | None = None
        # processor-name -> list of TTFB seconds
        self._ttfb: dict[str, list[float]] = {}

    def _now(self) -> float:
        if self._t0 is None:
            return 0.0
        return max(0.0, time.time() - self._t0)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame) and self._t0 is None:
            self._t0 = time.time()
        elif isinstance(frame, MetricsFrame):
            for d in frame.data or []:
                if isinstance(d, TTFBMetricsData) and d.value is not None:
                    self._ttfb.setdefault(d.processor, []).append(float(d.value))

        await self.push_frame(frame, direction)

    def latency_report(self) -> dict:
        """Summarize TTFB per processor + a flat headline for the dashboard."""
        per_service: dict[str, dict] = {}
        for proc, samples in self._ttfb.items():
            if not samples:
                continue
            per_service[proc] = {
                "count": len(samples),
                "mean_ms": round(mean(samples) * 1000),
                "p50_ms": round(_percentile(samples, 50) * 1000),
                "p90_ms": round(_percentile(samples, 90) * 1000),
                "max_ms": round(max(samples) * 1000),
            }

        def _service_mean_ms(needle: str) -> int | None:
            vals = [
                s for proc, samples in self._ttfb.items() if needle in proc.lower() for s in samples
            ]
            return round(mean(vals) * 1000) if vals else None

        return {
            "per_service": per_service,
            "llm_ttfb_mean_ms": _service_mean_ms("llm"),
            "stt_ttfb_mean_ms": _service_mean_ms("stt"),
            "tts_ttfb_mean_ms": _service_mean_ms("tts"),
        }

    def snapshot(self) -> dict:
        """Return the latency report + call duration captured so far."""
        report = self.latency_report()
        logger.info(
            "CallRecorder snapshot: duration {}s, LLM TTFB mean {}ms".format(
                round(self._now(), 1), report.get("llm_ttfb_mean_ms")
            )
        )
        return {
            "latency": report,
            "duration_secs": round(self._now(), 2),
        }
