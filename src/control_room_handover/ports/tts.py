"""The text-to-speech boundary for the spoken handover brief, from ``speech-lexicon-kit``.

The handover brief can be synthesised to audio for a spoken shift handover. Rather than redeclare
a speech port here, the boundary IS the shared kit's ``TextToSpeechPort`` (a ``runtime_checkable``
Protocol whose request / result types reference audio by URI and never carry the bytes), re-
exported once so this repo still has a single import site for the port set. The kit is pure
stdlib and holds no credential, so it imports on an air-gapped host; the adapter that resolves a
URI, holds a credential and picks a region is this repo's, per profile. TTS is OPTIONAL: the
offline adapter is a deterministic no-op that returns a reference and writes no audio, so the gate
and the demo exercise the seam without a voice backend.
"""

from __future__ import annotations

from speech_lexicon_kit.ports import (
    SpeechSynthesisRequest,
    SynthesisResult,
    TextToSpeechPort,
)

__all__ = [
    "SpeechSynthesisRequest",
    "SynthesisResult",
    "TextToSpeechPort",
]
