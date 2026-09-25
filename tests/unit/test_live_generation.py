"""The ``live`` profile: the laptop stack with a real local model behind the generation port.

Every test here is offline. The shared kit client takes an injected transport, so a scripted
fake stands in for the model server and the adapter is exercised through the same client a
presenter's laptop uses, retries and all.
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest
from hex_service_kit.localmodel import (
    LocalModelClient,
    LocalModelSettings,
    LocalModelUnavailable,
)

from control_room_handover.adapters.live.generation import LocalModelGenerationAdapter
from control_room_handover.adapters.local.identity import LocalIdentityAdapter
from control_room_handover.config import (
    DEFAULT_BINDINGS,
    LIVE_PROFILE,
    ProfileChoice,
    build_container,
)
from control_room_handover.domain.errors import NarrationDiscardedError
from control_room_handover.domain.handover_service import HandoverService
from control_room_handover.domain.models import LlmMessage, LlmRequest
from control_room_handover.ports import PORT_PROTOCOLS

from tests.conftest import local_settings
from tests.fixtures import sample_cases

_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "used_source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}

_SERVED_MODEL = "local-test-model"


class FakeServer:
    """Answers each chat call with the next scripted reply and records what it was sent."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes | None, timeout: float) -> bytes:
        assert body is not None
        payload = json.loads(body)
        self.calls.append(payload)
        reply = {
            "model": _SERVED_MODEL,
            "choices": [{"message": {"content": self.replies.pop(0)}}],
            "usage": {},
        }
        return json.dumps(reply).encode()


def _adapter(server: FakeServer) -> LocalModelGenerationAdapter:
    client = LocalModelClient(LocalModelSettings(), transport=server)
    return LocalModelGenerationAdapter(local_settings(profile=LIVE_PROFILE), client=client)


def _request(**overrides: Any) -> LlmRequest:
    base: dict[str, Any] = {
        "messages": (
            LlmMessage(role="system", content="You narrate a shift handover."),
            LlmMessage(role="user", content="FIGURES: [f1.recon] queue 320"),
        ),
        "response_schema": _SCHEMA,
    }
    base.update(overrides)
    return LlmRequest(**base)


def test_a_fenced_invalid_first_answer_is_corrected_and_the_value_returned() -> None:
    server = FakeServer(
        [
            '```json\n{"used_source_ids": ["f1.recon"]}\n```',
            'Sure:\n```json\n{"summary": "Recon queue at 320.", "used_source_ids": []}\n```',
        ]
    )
    response = _adapter(server).generate(_request())

    assert json.loads(response.text) == {"summary": "Recon queue at 320.", "used_source_ids": []}
    assert response.model == _SERVED_MODEL, "the id that ANSWERED, not a configured guess"
    assert len(server.calls) == 2, "the missing 'summary' must be fed back and retried"
    retry = server.calls[1]["messages"][-1]["content"]
    assert "summary" in retry


def test_the_request_is_mapped_through_unchanged() -> None:
    server = FakeServer(['{"summary": "ok"}'])
    _adapter(server).generate(_request(temperature=0.0, max_output_tokens=321))

    sent = server.calls[0]
    assert sent["temperature"] == 0.0
    assert sent["max_tokens"] == 321
    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["system", "user"]
    assert "JSON Schema" in sent["messages"][0]["content"], "the schema rides in the prompt"


def test_a_schemaless_request_returns_the_text_as_given() -> None:
    server = FakeServer(["A plain narration."])
    response = _adapter(server).generate(_request(response_schema=None))
    assert response.text == "A plain narration."
    assert len(server.calls) == 1


def test_no_valid_answer_is_a_discarded_narration() -> None:
    server = FakeServer(["no json here", "still none", "nor here"])
    with pytest.raises(NarrationDiscardedError, match="3 attempts"):
        _adapter(server).generate(_request())


def test_an_absent_server_raises_unavailable_with_the_start_recipe() -> None:
    def refuse(url: str, body: bytes | None, timeout: float) -> bytes:
        raise urllib.error.URLError("connection refused")

    client = LocalModelClient(LocalModelSettings(), transport=refuse)
    adapter = LocalModelGenerationAdapter(local_settings(profile=LIVE_PROFILE), client=client)
    with pytest.raises(LocalModelUnavailable, match="mlx_vlm.server"):
        adapter.generate(_request())


def test_the_handover_falls_back_when_the_server_is_down() -> None:
    """A narrator failure never fails the handover, in live exactly as in local."""

    def refuse(url: str, body: bytes | None, timeout: float) -> bytes:
        raise urllib.error.URLError("connection refused")

    container = build_container(local_settings(profile=LIVE_PROFILE))
    client = LocalModelClient(LocalModelSettings(), transport=refuse)
    service = HandoverService(
        ops_feeds=container.ops_feeds,
        generation=LocalModelGenerationAdapter(container.settings, client=client),
        audit=container.audit,
        tts=container.tts,
        tracer=container.tracer,
    )
    brief = service.build_handover(sample_cases.HANDOVER_REQUEST, actor="a")
    assert brief.narration_grounded is False
    assert brief.scorecard.total_queue_depth == 412


def test_the_container_builds_every_port_under_live() -> None:
    container = build_container(local_settings(profile=LIVE_PROFILE))
    for port, protocol in PORT_PROTOCOLS.items():
        assert isinstance(getattr(container, port), protocol), port
    assert isinstance(container.generation, LocalModelGenerationAdapter)


def test_live_binds_what_local_binds_except_the_model_port() -> None:
    differing = {
        port for port, table in DEFAULT_BINDINGS.items() if table["live"] != table["local"]
    }
    assert differing == {"generation"}


def test_live_takes_the_laptop_posture() -> None:
    choice = ProfileChoice(profile=LIVE_PROFILE, explicit=True)
    assert choice.exposure_profile == "local"
    assert choice.bind_profile == "local"
    # The seeded personas construct under a deliberate live, exactly as under local.
    LocalIdentityAdapter(local_settings(profile=LIVE_PROFILE))


def test_the_banner_names_the_local_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_MODEL", "some-org/some-local-model")
    assert local_settings(profile=LIVE_PROFILE).generator_model == "some-org/some-local-model"
