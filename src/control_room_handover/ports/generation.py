"""GenerationPort: the LLM boundary that NARRATES the scorecard and produces no number.

The managed adapter is a Gemini model on the Gemini Enterprise Agent Platform; the offline
adapter is a deterministic, schema-driven narrator with no model and no network; the exit
adapter fails fast. Whichever is bound, the contract is the same and the discipline is the same:
the model receives only the already-computed, PII-redacted evidence and writes prose over it. It
decides no queue depth, no breach count and no severity. The handover service schema-validates
the response and discards it (falling back to a deterministic summary) on any failure, so a
malformed or ungrounded narration can never reach a brief.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import LlmRequest, LlmResponse


@runtime_checkable
class GenerationPort(Protocol):
    def generate(self, request: LlmRequest) -> LlmResponse:
        """Generate a narration for ``request`` using the configured model, or raise."""
        ...
