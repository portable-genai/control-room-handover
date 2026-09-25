"""Managed GenerationPort: narrate the scorecard with a Gemini model (SDK imported lazily).

The primary adapter. It calls a Gemini model on the Gemini Enterprise Agent Platform to narrate
the already-computed scorecard; the model receives only the redacted evidence and produces prose,
never a number. The ``google.genai`` import is INSIDE the method, so the ``local`` and ``onprem``
profiles import this module with no SDK installed. The handover service schema-validates and
grounding-checks whatever comes back and discards it on any failure, so this adapter's output can
never smuggle a fabricated figure into a brief.
"""

from __future__ import annotations

from hex_service_kit import provenance

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse

_DEFAULT_MODEL = "gemini-3.5-flash"


class CloudGenerationAdapter:
    """Gemini-backed narrator for the managed profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, request: LlmRequest) -> LlmResponse:
        # Lazy import: the offline profiles must import this module with no genai SDK present.
        from google import genai  # noqa: PLC0415
        from google.genai import types  # noqa: PLC0415

        client = genai.Client()
        model = request.model or _DEFAULT_MODEL
        prompt = "\n\n".join(message.content for message in request.messages)
        config = types.GenerateContentConfig(
            max_output_tokens=request.max_output_tokens,
            response_mime_type="application/json",
            response_schema=request.response_schema,
        )
        if request.temperature is not None:
            # Free sampling is an ABSENT temperature, never 1.0: only a pinned call sends one.
            config.temperature = request.temperature
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        provenance.note_model(model)
        return LlmResponse(text=response.text or "", model=model)
