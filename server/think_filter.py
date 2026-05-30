"""Strip ``<think>...</think>`` spans from streamed LLM text before TTS.

Defensive safety net for reasoning models (Nemotron-3-Super). With thinking
enabled, reasoning normally streams in the separate ``reasoning_content``
channel, which pipecat never sends to TTS. But if the vLLM server is NOT
configured with a reasoning parser, the model instead emits its chain-of-thought
as ``<think>...</think>`` inside the normal ``content`` stream — and the bot
would speak it aloud.

This processor sits between the LLM and the TTS service and removes any
``<think>...</think>`` spans from the ``LLMTextFrame`` token stream. Because the
LLM streams token-by-token, the tags can be split across frames, so we keep a
small carry buffer and a simple inside/outside state machine across frames.

If the server DOES separate reasoning (or thinking is off), there are no tags in
the content stream and this filter is a transparent no-op.
"""

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

_OPEN = "<think>"
_CLOSE = "</think>"


def _partial_suffix_len(text: str, tag: str) -> int:
    """Length of the longest suffix of ``text`` that is a proper prefix of ``tag``.

    Used to hold back a partial tag (e.g. ``"<thi"``) that might complete on the
    next streamed frame, so we never emit half a tag to TTS.
    """
    max_k = min(len(tag) - 1, len(text))
    for k in range(max_k, 0, -1):
        if text.endswith(tag[:k]):
            return k
    return 0


class ThinkTagFilter(FrameProcessor):
    """Remove ``<think>...</think>`` spans from the LLM text stream."""

    def __init__(self):
        super().__init__()
        self._inside = False
        self._carry = ""

    def _reset(self) -> None:
        self._inside = False
        self._carry = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # New response: reset state so a stuck "inside" never leaks across turns.
        if isinstance(frame, (LLMFullResponseStartFrame, LLMFullResponseEndFrame)):
            self._reset()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMTextFrame):
            cleaned = self._strip(frame.text)
            if cleaned:
                await self.push_frame(LLMTextFrame(cleaned), direction)
            return

        await self.push_frame(frame, direction)

    def _strip(self, text: str) -> str:
        buf = self._carry + text
        self._carry = ""
        out: list[str] = []
        i = 0
        n = len(buf)

        while i < n:
            if not self._inside:
                idx = buf.find(_OPEN, i)
                if idx == -1:
                    keep = _partial_suffix_len(buf[i:], _OPEN)
                    out.append(buf[i : n - keep] if keep else buf[i:])
                    self._carry = buf[n - keep :] if keep else ""
                    break
                out.append(buf[i:idx])
                i = idx + len(_OPEN)
                self._inside = True
            else:
                idx = buf.find(_CLOSE, i)
                if idx == -1:
                    # Still inside the think block; drop content but hold a
                    # partial closing tag so it can complete next frame.
                    keep = _partial_suffix_len(buf[i:], _CLOSE)
                    self._carry = buf[n - keep :] if keep else ""
                    break
                i = idx + len(_CLOSE)
                self._inside = False

        return "".join(out)
