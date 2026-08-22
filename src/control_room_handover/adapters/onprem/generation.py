"""On-prem GenerationPort: fail-fast portability placeholder (the sovereign-exit proof, P-12).

The client runs its own model behind its own boundary, so this binding refuses at call time. A
placeholder that returned canned prose would let a handover ship a narration nobody's model wrote;
refusing is the honest failure, and the deterministic scorecard still stands on its own.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse


class OnPremGenerationAdapter:
    """Satisfies GenerationPort but refuses: bind the client's own model endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, request: LlmRequest) -> LlmResponse:
        raise NotImplementedError(
            "on-prem narration is a portability placeholder: bind the client's own model "
            "endpoint (see docs/onprem-migration.md). The scorecard is deterministic and needs "
            "no model; only the narrative does."
        )
