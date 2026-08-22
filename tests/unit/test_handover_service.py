"""The handover pipeline: deterministic scorecard, grounded narration, redact-before-audit."""

from __future__ import annotations

from control_room_handover.config import (
    Settings,
    build_container,
)
from control_room_handover.domain.handover_service import (
    HandoverService,
)
from control_room_handover.domain.kernel import (
    Decision,
    Severity,
)
from control_room_handover.domain.models import (
    FeedId,
    HandoverRequest,
    LlmRequest,
    LlmResponse,
)

from tests.fixtures import sample_cases


def _service(container: object | None = None) -> HandoverService:
    c = container or build_container(Settings(profile="local", audit_path=":memory:"))
    return HandoverService(
        ops_feeds=c.ops_feeds,  # type: ignore[attr-defined]
        generation=c.generation,  # type: ignore[attr-defined]
        audit=c.audit,  # type: ignore[attr-defined]
        tts=c.tts,  # type: ignore[attr-defined]
        tracer=c.tracer,  # type: ignore[attr-defined]
    )


def test_the_scorecard_numbers_are_engine_owned_and_deterministic() -> None:
    brief = _service().build_handover(sample_cases.HANDOVER_REQUEST, actor="a")
    card = brief.scorecard
    # The golden fixtures' last-day figures, computed independently in the fixture generator.
    assert card.total_queue_depth == 412
    assert card.total_sla_breached == 88
    assert card.overall_severity is Severity.CRITICAL
    by_feed = {c.feed_id: c for c in card.feeds}
    recon = by_feed[FeedId.RECON_BREAKS]
    assert recon.queue_depth == 320
    assert recon.sla_breached == 80
    assert recon.capacity == 160
    assert recon.capacity_callout is True
    assert recon.severity is Severity.CRITICAL
    assert recon.anomalies, "the last-day queue / breach spike must be flagged"
    disputes = by_feed[FeedId.DISPUTES]
    assert disputes.capacity_callout is False
    assert disputes.severity is Severity.MEDIUM


def test_the_pipeline_is_byte_identical_on_replay() -> None:
    first = _service().build_handover(sample_cases.HANDOVER_REQUEST, actor="a")
    second = _service().build_handover(sample_cases.HANDOVER_REQUEST, actor="a")
    assert first.scorecard == second.scorecard


def test_a_handover_always_requires_sign_off() -> None:
    brief = _service().build_handover(sample_cases.HANDOVER_REQUEST, actor="a")
    assert brief.requires_human_review is True
    assert brief.decision is Decision.ESCALATED


def test_the_narration_is_grounded_and_carries_no_invented_number() -> None:
    brief = _service().build_handover(sample_cases.HANDOVER_REQUEST, actor="a")
    assert brief.narration_grounded is True
    assert brief.summary.strip()


def test_an_ungrounded_narration_is_discarded_for_the_deterministic_summary() -> None:
    """A model that invents a figure the engine never produced must not reach the brief."""

    class _Liar:
        def generate(self, request: LlmRequest) -> LlmResponse:
            return LlmResponse(text='{"summary": "backlog is 999999 items"}', model="liar")

    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = HandoverService(
        ops_feeds=container.ops_feeds,
        generation=_Liar(),
        audit=container.audit,
        tts=container.tts,
        tracer=container.tracer,
    )
    brief = service.build_handover(sample_cases.HANDOVER_REQUEST, actor="a")
    assert brief.narration_grounded is False
    assert "999999" not in brief.summary


def test_pii_is_redacted_before_the_audit_write() -> None:
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    audit = container.audit
    _service(container).build_handover(sample_cases.HANDOVER_REQUEST, actor=sample_cases.ACTOR)
    records = audit.log.read_all()  # type: ignore[attr-defined]
    assert records, "an audit event should have been recorded"
    assert records[-1]["actor"] == sample_cases.ACTOR
    assert audit.log.verify_chain().ok  # type: ignore[attr-defined]


def test_an_out_of_range_lookback_is_refused() -> None:
    import pytest

    from control_room_handover.domain.errors import FeedContractError

    with pytest.raises(FeedContractError):
        HandoverRequest(shift_id="x", as_of="2026-08-07", lookback_days=0)
