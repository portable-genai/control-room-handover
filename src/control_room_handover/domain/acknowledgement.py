"""The shift-acknowledgement clock: a pure function over a routed handover (slice 5).

A handover is not done when it is written; it is done when the INCOMING shift lead signs off. So
a routed brief sits ``PENDING`` on a deadline clock, becomes ``ACKNOWLEDGED`` when a sign-off is
recorded, and ``BREACHED`` if the window elapses with no sign-off. The transition is deterministic
(the ``as_of`` and the sign-off time are inputs, never a wall clock read here), so the same facts
always yield the same state and a test can drive the pending path red before the clock exists and
green after.
"""

from __future__ import annotations

from datetime import datetime

from .errors import FeedContractError
from .models import AcknowledgementStatus, AckState

#: How long the incoming shift lead has to acknowledge before the handover breaches its clock.
#: Policy config in spirit; a follow-up lifts it into ``settings.yaml`` alongside the SLA bands.
DEFAULT_ACK_DEADLINE_MINUTES = 30


def acknowledgement_status(
    routed_at: datetime,
    now: datetime,
    *,
    acknowledged_at: datetime | None = None,
    acknowledged_by: str = "",
    deadline_minutes: int = DEFAULT_ACK_DEADLINE_MINUTES,
) -> AcknowledgementStatus:
    """Resolve where a routed handover sits against its acknowledgement clock.

    ``routed_at`` and ``now`` (and ``acknowledged_at`` when present) are supplied by the caller,
    so this stays a pure function: no clock is read here. A sign-off recorded at or before ``now``
    wins regardless of the deadline (a late sign-off still acknowledges); with no sign-off the
    state is ``PENDING`` inside the window and ``BREACHED`` past it.
    """
    if deadline_minutes < 1:
        raise FeedContractError("deadline_minutes must be >= 1")
    elapsed = int((now - routed_at).total_seconds() // 60)
    if elapsed < 0:
        raise FeedContractError("now must not precede routed_at")
    if acknowledged_at is not None and acknowledged_at <= now:
        return AcknowledgementStatus(
            state=AckState.ACKNOWLEDGED,
            minutes_elapsed=elapsed,
            deadline_minutes=deadline_minutes,
            acknowledged_by=acknowledged_by,
        )
    state = AckState.BREACHED if elapsed > deadline_minutes else AckState.PENDING
    return AcknowledgementStatus(
        state=state,
        minutes_elapsed=elapsed,
        deadline_minutes=deadline_minutes,
        acknowledged_by="",
    )
