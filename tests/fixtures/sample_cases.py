"""Canonical synthetic fixtures, shared by the unit and contract suites.

Every party is obviously fictional and every identifier is synthetic. One canonical handover
request and one canonical brief are enough for the contract suite: parity means the SAME request
through every implementation, so the request has to have one home rather than being retyped per
test. ``brief_with_pii`` plants a synthetic identifier in a citation snippet so the redact-before-
the-wire proofs have an independent literal to look for.
"""

from __future__ import annotations

from control_room_handover.domain.kernel import Citation, Decision, Severity
from control_room_handover.domain.models import (
    AGING_BUCKET_LABELS,
    AgingBucket,
    ControlRoomScorecard,
    FeedId,
    FeedScorecard,
    HandoverBrief,
    HandoverRequest,
)

#: The verified principal the tests attribute work to (never a client-asserted actor).
ACTOR = "analyst@bank.example"

#: A tenant partition, so the outbound-review assertions are not all on the empty string.
TENANT = "demo-bank"

#: A planted identifier, so a redaction assertion has an independent literal to look for rather
#: than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

#: The canonical handover ask, aligned to the golden export fixtures' last ``as_of``.
HANDOVER_REQUEST = HandoverRequest(shift_id="asia-day", as_of="2026-08-07", lookback_days=14)

#: A routine request that reads the same fixtures; the handover always escalates for sign-off, so
#: there is no "non-escalating" handover, but the shorter lookback exercises the window slicing.
ROUTINE_REQUEST = HandoverRequest(shift_id="asia-night", as_of="2026-08-07", lookback_days=3)


def _aging(counts: tuple[int, int, int, int]) -> tuple[AgingBucket, ...]:
    pairs = zip(AGING_BUCKET_LABELS, counts, strict=True)
    return tuple(AgingBucket(label=label, count=c) for label, c in pairs)


def sample_scorecard() -> ControlRoomScorecard:
    """A minimal, hand-built scorecard, so a brief can be constructed without the whole pipeline."""
    citation = Citation(source_id="recon_breaks", title="Ops worklist export", snippet="urgent")
    feed = FeedScorecard(
        feed_id=FeedId.RECON_BREAKS,
        as_of="2026-08-07",
        queue_depth=320,
        aging=_aging((130, 90, 60, 40)),
        sla_breached=80,
        sla_breach_rate=0.25,
        throughput=140,
        drain_ratio=0.4375,
        capacity=160,
        capacity_utilisation=2.0,
        capacity_callout=True,
        severity=Severity.CRITICAL,
        anomalies=(),
        citations=(citation,),
    )
    return ControlRoomScorecard(
        as_of="2026-08-07",
        feeds=(feed,),
        total_queue_depth=320,
        total_sla_breached=80,
        overall_severity=Severity.CRITICAL,
        citations=(citation,),
    )


def sample_brief(
    *, snippet: str = "urgent", severity: Severity = Severity.CRITICAL
) -> HandoverBrief:
    """A canonical handover brief. ``snippet`` seeds the citation so a PII proof can plant one."""
    scorecard = sample_scorecard()
    citation = Citation(source_id="recon_breaks", title="Ops worklist export", snippet=snippet)
    return HandoverBrief(
        subject="Shift handover asia-day as of 2026-08-07",
        severity=severity,
        decision=Decision.ESCALATED,
        summary="Operations shift handover; figures are engine-computed and cited.",
        requires_human_review=True,
        scorecard=scorecard,
        citations=(citation,),
    )


#: A JSON body for the handover endpoint, so the auth-posture suites have a valid request.
def handover_body(request: HandoverRequest = HANDOVER_REQUEST) -> dict[str, object]:
    return {
        "shift_id": request.shift_id,
        "as_of": request.as_of,
        "lookback_days": request.lookback_days,
    }


def brief_with_pii() -> HandoverBrief:
    """A brief carrying a synthetic national id in a citation snippet, for redaction proofs."""
    return sample_brief(snippet=f"break tied to NRIC {PLANTED_NRIC} on file")
