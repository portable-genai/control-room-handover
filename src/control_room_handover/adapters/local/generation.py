"""Local GenerationPort: a deterministic, schema-driven narrator (SDK-free, no network).

The ``local`` profile's stand-in for Gemini: no model, no network, fully reproducible. It reads
``request.response_schema`` and emits a JSON object whose keys match it, with ``used_source_ids``
mapped from the ``[source_id]`` headers in the rendered FIGURES block so the narration cites only
sources the engine actually computed over, and a summary that states only the shape of the
handover, never a fabricated number. There is no offline Gemini emulator, so this path is
unconditional. The engine decides the numbers; this only narrates.
"""

from __future__ import annotations

import json
import re

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse

_SOURCE_HEADER_RE = re.compile(r"\[([a-z0-9][a-z0-9_.\-]*?)\]")

#: A deterministic narration that introduces NO figure of its own (so the grounding check passes
#: whatever the scorecard's numbers are). It describes the handover in words only.
_SUMMARY = (
    "Operations shift handover. Backlog, SLA-breach and throughput figures are as computed by "
    "the deterministic scorecard engine and cited to their source feeds; anomalies flagged by "
    "the robust-z detector are called out per feed. This handover requires the incoming shift "
    "lead's acknowledgement before the outgoing shift stands down."
)


class LocalDeterministicGenerationAdapter:
    """Deterministic narrator whose ``generate`` returns JSON matching the request schema."""

    MODEL = "offline-deterministic"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, request: LlmRequest) -> LlmResponse:
        source_ids = self._source_ids(request)
        body = {"summary": _SUMMARY, "used_source_ids": source_ids}
        return LlmResponse(text=json.dumps(body), model=self.MODEL)

    @staticmethod
    def _source_ids(request: LlmRequest) -> list[str]:
        user = ""
        for message in reversed(request.messages):
            if message.role == "user":
                user = message.content
                break
        seen: list[str] = []
        for sid in _SOURCE_HEADER_RE.findall(user):
            if sid not in seen:
                seen.append(sid)
        return seen
