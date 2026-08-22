"""On-prem TextToSpeechPort: fail-fast portability placeholder (the sovereign-exit proof, P-12).

The client runs its own speech backend on premises, so this binding refuses at call time. TTS is
optional and the handover service treats a synthesis failure as a dropped enrichment, so refusing
here degrades the brief to text rather than failing the handover, which is the correct behaviour
for an unimplemented optional seam.
"""

from __future__ import annotations

from speech_lexicon_kit.ports import SpeechSynthesisRequest, SynthesisResult

from ...config import Settings


class OnPremTtsAdapter:
    """Satisfies TextToSpeechPort but refuses: bind the client's own speech backend."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def synthesize(self, request: SpeechSynthesisRequest) -> SynthesisResult:
        raise NotImplementedError(
            "on-prem speech synthesis is a portability placeholder: bind the client's own "
            "text-to-speech backend (see docs/onprem-migration.md)."
        )
