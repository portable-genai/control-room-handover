"""Live GenerationPort: narrate the scorecard with the laptop's local open-weight model.

The ``live`` profile binds every port to its ``local`` adapter except this one, which calls the
fleet's shared local model server (OpenAI-compatible ``/chat/completions``, Gemma 4 31B by
default) through ``hex_service_kit.localmodel``. The kit client owns what every local server gets
wrong: it states the schema in the prompt, strips a markdown fence, validates the answer against
the request's JSON Schema and feeds a failure back for a corrected reply. This adapter only maps
the port's request and response onto it.

The discipline is the managed adapter's: the model receives only the already-computed, redacted
evidence and writes prose over it. The handover service still schema-validates and
grounding-checks the returned text and falls back to the deterministic summary on any failure,
so a local model can no more smuggle a figure into a brief than Gemini can.

No SDK and no network at construction: the client is built from the three-state
``LOCAL_MODEL_URL`` / ``LOCAL_MODEL`` / ``LOCAL_MODEL_TIMEOUT`` settings and first speaks to the
server when a narration is requested.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hex_service_kit.localmodel import (
    LocalModelClient,
    LocalModelOutputError,
    LocalModelSettings,
    LocalModelUnavailable,
)

from ...config import Settings
from ...domain.errors import NarrationDiscardedError
from ...domain.models import LlmRequest, LlmResponse

_log = logging.getLogger(__name__)

#: The port's roles onto the chat-completions roles. ``model`` is Gemini's name for the
#: assistant turn; anything unrecognised is sent as the user's words, never as a system turn.
_ROLES = {"system": "system", "user": "user", "model": "assistant", "assistant": "assistant"}


class LocalModelGenerationAdapter:
    """Kit-backed narrator for the ``live`` profile."""

    def __init__(self, settings: Settings, *, client: LocalModelClient | None = None) -> None:
        self._settings = settings
        self._client = client or LocalModelClient(LocalModelSettings.from_env())

    def generate(self, request: LlmRequest) -> LlmResponse:
        # request.model names a managed model id when a caller pins one; the laptop lane serves
        # exactly one local model, so the id that answers is the server's, reported below.
        messages: list[dict[str, Any]] = [
            {"role": _ROLES.get(message.role, "user"), "content": message.content}
            for message in request.messages
        ]
        try:
            if request.response_schema is not None:
                completion = self._client.complete_json(
                    messages,
                    schema=request.response_schema,
                    temperature=request.temperature,
                    max_tokens=request.max_output_tokens,
                )
                # The validated value, re-serialised: the raw text may still carry the fence or
                # the sentence the kit stripped, and the service parses this as JSON.
                text = json.dumps(completion.data)
            else:
                completion = self._client.complete(
                    messages,
                    temperature=request.temperature,
                    max_tokens=request.max_output_tokens,
                )
                text = completion.text
        except LocalModelUnavailable:
            # The service falls back to the deterministic summary on any narrator failure, so
            # this line is the presenter's only sign that the model server is down; the kit's
            # message ends with the two lines that start one.
            _log.warning("live narration unavailable", exc_info=True)
            raise
        except LocalModelOutputError as exc:
            raise NarrationDiscardedError(
                f"the local model gave no schema-valid narration in {exc.attempts} attempts"
            ) from exc
        return LlmResponse(text=text, model=completion.model)
