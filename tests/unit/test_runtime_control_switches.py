"""Review routing has a switch, default on, and every caller says what happened to a hand-off.

The fleet's runtime-control contract (2026-09-24). Review routing is the one cheap runtime
control this service has: ``CONTROLROOM_REVIEW_ROUTING`` is read in three states; off binds a
disabled router and says so at startup; on under the managed profile refuses to boot without a
console; and the API, the agent tool and the CLI report ``review_routing`` rather than failing
an already-built handover when the console is unreachable.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from control_room_handover.adapters.controls import (
    DisabledReviewRouter,
    RecordingReviewRouter,
    ReviewRouting,
)
from control_room_handover.agent import tools
from control_room_handover.cli.main import main as cli_main
from control_room_handover.config import (
    REVIEW_ROUTING_ENV,
    Container,
    ControlSwitches,
    ProfileChoice,
    Settings,
    build_container,
    warn_switched_off,
)
from control_room_handover.domain.handover_service import HandoverService
from control_room_handover.domain.models import HandoverBrief
from control_room_handover.envread import ConfiguredEmptyError

from tests.conftest import LOOPBACK_PEER, local_settings, reimport
from tests.fixtures import sample_cases

_AUDITOR = {"X-Dev-Persona": "auditor"}
_LOCAL_ROUTE = "control_room_handover.adapters.local.review_router.LocalReviewRouter.route"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REVIEW_ROUTING_ENV, raising=False)
    monkeypatch.delenv("HUMAN_REVIEW_URL", raising=False)


def _client() -> TestClient:
    """A fresh local app, so its per-process container reads this test's posture."""
    return TestClient(reimport("control_room_handover.api.app").app, client=LOOPBACK_PEER)


def _brief() -> HandoverBrief:
    container = build_container(local_settings())
    brief = HandoverService(
        ops_feeds=container.ops_feeds,
        generation=container.generation,
        audit=container.audit,
        tts=container.tts,
        tracer=container.tracer,
    ).build_handover(sample_cases.HANDOVER_REQUEST, actor=sample_cases.ACTOR)
    assert brief.requires_human_review
    return brief


def _managed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "control_room_handover.config.resolve_profile",
        lambda environ=None: ProfileChoice(profile="gcp", explicit=True),
    )


class _Accepting:
    def route(self, result: HandoverBrief, *, maker: str, tenant: str = "") -> str:
        return "review-1"


class _Refusing:
    def route(self, result: HandoverBrief, *, maker: str, tenant: str = "") -> str:
        raise ConnectionError("console unreachable")


# --------------------------------------------------------------------------- #
# Three states
# --------------------------------------------------------------------------- #
def test_routing_is_on_when_nothing_is_said() -> None:
    assert Settings.load().controls == ControlSwitches(review_routing=True)


def test_routing_switched_off_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert Settings.load().controls.switched_off() == (REVIEW_ROUTING_ENV,)


def test_an_emptied_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "")
    with pytest.raises(ConfiguredEmptyError, match=REVIEW_ROUTING_ENV):
        Settings.load()


def test_an_unrecognised_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "sometimes")
    with pytest.raises(ValueError, match=REVIEW_ROUTING_ENV):
        Settings.load()


# --------------------------------------------------------------------------- #
# Off binds the disabled router, and says so once
# --------------------------------------------------------------------------- #
def test_off_binds_the_disabled_router() -> None:
    settings = local_settings(controls=ControlSwitches(review_routing=False))
    assert isinstance(Container(settings).review_router, DisabledReviewRouter)


def test_on_binds_the_profile_router() -> None:
    assert not isinstance(Container(local_settings()).review_router, DisabledReviewRouter)


def test_the_off_posture_is_logged_once_however_many_containers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    warn_switched_off.cache_clear()
    settings = local_settings(controls=ControlSwitches(review_routing=False))
    with caplog.at_level(logging.WARNING, logger="control_room_handover.config"):
        for _ in range(3):
            build_container(settings)
    assert caplog.text.count(REVIEW_ROUTING_ENV) == 1


# --------------------------------------------------------------------------- #
# On has to work: checked at boot under the managed profile
# --------------------------------------------------------------------------- #
def test_routing_on_under_gcp_without_a_console_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _managed(monkeypatch)
    with pytest.raises(ConfiguredEmptyError, match="HUMAN_REVIEW_URL"):
        Settings.load()


def test_routing_stated_off_under_gcp_needs_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    _managed(monkeypatch)
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "false")
    assert Settings.load().controls.review_routing is False


def test_routing_on_under_gcp_with_a_console_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    _managed(monkeypatch)
    monkeypatch.setenv("HUMAN_REVIEW_URL", "https://review.example.test")
    assert Settings.load().review_url == "https://review.example.test"


# --------------------------------------------------------------------------- #
# The four routing outcomes
# --------------------------------------------------------------------------- #
def test_routing_outcomes_take_each_of_their_four_values() -> None:
    brief = _brief()

    unrequired = RecordingReviewRouter(_Accepting())
    assert (
        unrequired.route(dataclasses.replace(brief, requires_human_review=False), maker="m") == ""
    )
    assert unrequired.outcome is ReviewRouting.NOT_REQUIRED

    routed = RecordingReviewRouter(_Accepting())
    assert routed.route(brief, maker="m") == "review-1"
    assert routed.outcome is ReviewRouting.ROUTED

    off = RecordingReviewRouter(DisabledReviewRouter(local_settings()))
    assert off.route(brief, maker="m") == ""
    assert off.outcome is ReviewRouting.OFF

    failed = RecordingReviewRouter(_Refusing())
    assert failed.route(brief, maker="m") == ""
    assert failed.outcome is ReviewRouting.FAILED


def test_a_failed_hand_off_is_reported_and_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = RecordingReviewRouter(_Refusing())
    with caplog.at_level(logging.WARNING, logger="control_room_handover.adapters.controls"):
        assert failed.route(_brief(), maker="m") == ""
    assert failed.outcome is ReviewRouting.FAILED
    assert "ConnectionError" in caplog.text


# --------------------------------------------------------------------------- #
# Every caller reports it: the API, the agent tool, the CLI
# --------------------------------------------------------------------------- #
def _handover(client: TestClient) -> Any:
    return client.post("/v1/handover", json=sample_cases.handover_body(), headers=_AUDITOR)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with _client() as c:
        yield c


def test_the_api_reports_a_routed_hand_off(client: TestClient) -> None:
    body = _handover(client).json()
    assert body["review_routing"] == "routed"
    assert body["review_ref"]


def test_the_api_reports_routing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    with _client() as client:
        body = _handover(client).json()
    assert body["review_routing"] == "off"
    assert body["review_ref"] == ""


def test_the_api_reports_a_failed_hand_off_instead_of_failing_the_request(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setattr(_LOCAL_ROUTE, _Refusing.route)
    response = _handover(client)
    assert response.status_code == 200
    assert response.json()["review_routing"] == "failed"
    assert response.json()["review_ref"] == ""


def test_the_agent_tool_reports_the_hand_off(monkeypatch: pytest.MonkeyPatch) -> None:
    request = sample_cases.HANDOVER_REQUEST
    settings = local_settings()
    payload = tools.build_shift_handover(request.shift_id, request.as_of, settings=settings)
    assert payload["review_routing"] == "routed"

    monkeypatch.setattr(_LOCAL_ROUTE, _Refusing.route)
    failed = tools.build_shift_handover(request.shift_id, request.as_of, settings=settings)
    assert failed["review_routing"] == "failed"
    assert failed["review_ref"] == ""


def test_the_cli_reports_the_hand_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    request = sample_cases.HANDOVER_REQUEST
    assert cli_main(["handover", request.shift_id, request.as_of]) == 0
    assert "hand-off: routed" in capsys.readouterr().out

    monkeypatch.setattr(_LOCAL_ROUTE, _Refusing.route)
    assert cli_main(["handover", request.shift_id, request.as_of]) == 0
    assert "hand-off: failed" in capsys.readouterr().out
