"""Local TextToSpeechPort: a deterministic no-op that returns a reference and writes no audio.

TTS is optional. The offline profile exercises the seam without a voice backend: it returns a
:class:`SynthesisResult` referencing a synthetic ``local://`` URI and never produces bytes, so the
gate and the demo can prove the handover flows through the port without holding a customer's voice
or reaching a network. It is a no-op in EFFECT (no audio), not in CONTRACT (it returns a valid
result), so a caller that depended on a reference still gets one.
"""

from __future__ import annotations

from speech_lexicon_kit.ports import (
    AudioRef,
    SpeechSynthesisRequest,
    SynthesisResult,
)

from ...config import Settings


class LocalNoOpTtsAdapter:
    """Deterministic no-op synthesizer: a reference, no audio, no network."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def synthesize(self, request: SpeechSynthesisRequest) -> SynthesisResult:
        ref = AudioRef(
            uri=f"local://handover-audio/{request.request_id}",
            media_type=request.audio_encoding,
        )
        return SynthesisResult(
            request_id=request.request_id,
            audio=ref,
            voice=request.voice,
            characters_billed=len(request.text),
        )
