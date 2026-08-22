"""Rule R8: a reviewed handover is ROUTED to Hrz7, not left in a per-repo boolean.

This is the standing gate for the failure the rule exists to prevent. A repo can set
``requires_human_review = True``, pass every other test, and still auto-execute in practice
because nothing ever reads the flag. So the assertions here are about the ROUTING, not the flag:
a handover produces an outbound review, the payload leaves redacted, a critical handover demands
dual control, and the on-prem placeholder refuses rather than swallowing the escalation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from control_room_handover.adapters.gcp.review_router import (
    CloudReviewRouter,
)
from control_room_handover.adapters.local.review_router import (
    LocalReviewRouter,
)
from control_room_handover.adapters.onprem.review_router import (
    OnPremReviewRouter,
)
from control_room_handover.api.app import (
    app,
)
from control_room_handover.config import (
    Settings,
)
from control_room_handover.domain.kernel import (
    Severity,
)

from tests.fixtures import sample_cases


def _settings(profile: str = "local") -> Settings:
    return Settings(profile=profile, audit_path=":memory:", tenant="demo-bank")


def test_a_reviewed_handover_produces_an_outbound_review() -> None:
    router = LocalReviewRouter(_settings())
    brief = sample_cases.sample_brief(severity=Severity.HIGH)
    ref = router.route(brief, maker="analyst@bank.example")
    assert ref, "routing must return a reference, so the caller can record where it went"
    pending = router.outbox.pending()
    assert len(pending) == 1
    review = pending[0].review
    assert review.maker == "analyst@bank.example"
    assert review.tenant == "demo-bank"
    assert review.severity == Severity.HIGH.value
    assert review.required_approvals == 1
    assert review.source_key, "a durable outbox needs an idempotency key"


def test_a_critical_handover_demands_dual_control() -> None:
    router = LocalReviewRouter(_settings())
    brief = sample_cases.sample_brief(severity=Severity.CRITICAL)
    router.route(brief, maker="analyst@bank.example")
    assert router.outbox.pending()[0].review.required_approvals == 2


def test_the_payload_is_redacted_before_it_leaves_the_process() -> None:
    """Hrz7 is a shared sink; a raw identifier must never reach the wire."""
    router = LocalReviewRouter(_settings())
    router.route(sample_cases.brief_with_pii(), maker="analyst@bank.example")
    review = router.outbox.pending()[0].review
    wire = repr(review.to_payload())
    assert sample_cases.PLANTED_NRIC not in wire
    assert "REDACTED" in wire


def test_the_managed_router_refuses_when_no_console_is_configured() -> None:
    """An escalation with nowhere to go must fail loudly, not return as if it were reviewed."""
    router = CloudReviewRouter(Settings(profile="gcp", audit_path=":memory:", review_url=""))
    with pytest.raises(RuntimeError, match="R8"):
        router.route(sample_cases.sample_brief(), maker="analyst@bank.example")


def test_the_onprem_placeholder_refuses_rather_than_dropping_the_escalation() -> None:
    router = OnPremReviewRouter(_settings("onprem"))
    with pytest.raises(NotImplementedError, match="R8"):
        router.route(sample_cases.sample_brief(), maker="analyst@bank.example")


def test_the_api_routes_the_handover_in_the_same_request() -> None:
    """The serving path, not just the adapter: a handover must not depend on a later job."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    body = client.post(
        "/v1/handover",
        json=sample_cases.handover_body(),
        headers={"X-Dev-Persona": "auditor"},
    ).json()
    assert body["requires_human_review"] is True
    assert body["review_ref"], "a handover with no routing reference went nowhere"
