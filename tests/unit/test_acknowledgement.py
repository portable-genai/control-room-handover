"""The shift-acknowledgement clock (slice 5): pending, acknowledged, breached, all deterministic.

An unacknowledged handover must stay PENDING on a clock and cross to BREACHED when the window
elapses; a recorded sign-off wins. The red-before / green-after proof is explicit: inside the
window with no sign-off is PENDING, and the SAME facts one minute past the deadline are BREACHED,
so a clock that never breached would fail here.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from control_room_handover.domain.acknowledgement import (
    DEFAULT_ACK_DEADLINE_MINUTES,
    acknowledgement_status,
)
from control_room_handover.domain.errors import FeedContractError
from control_room_handover.domain.models import AckState

_ROUTED = datetime(2026, 8, 7, 9, 0, 0)


def test_inside_the_window_with_no_sign_off_is_pending() -> None:
    status = acknowledgement_status(_ROUTED, _ROUTED + timedelta(minutes=10))
    assert status.state is AckState.PENDING
    assert status.minutes_elapsed == 10


def test_past_the_window_with_no_sign_off_is_breached() -> None:
    late = _ROUTED + timedelta(minutes=DEFAULT_ACK_DEADLINE_MINUTES + 1)
    status = acknowledgement_status(_ROUTED, late)
    assert status.state is AckState.BREACHED


def test_a_recorded_sign_off_acknowledges_even_when_late() -> None:
    late = _ROUTED + timedelta(minutes=DEFAULT_ACK_DEADLINE_MINUTES + 5)
    status = acknowledgement_status(
        _ROUTED,
        late,
        acknowledged_at=late,
        acknowledged_by="incoming-lead@bank.example",
    )
    assert status.state is AckState.ACKNOWLEDGED
    assert status.acknowledged_by == "incoming-lead@bank.example"


def test_the_pending_and_breached_states_come_from_the_same_facts_one_minute_apart() -> None:
    """Red-before / green-after: the clock must actually change state at the deadline."""
    just_inside = acknowledgement_status(
        _ROUTED, _ROUTED + timedelta(minutes=DEFAULT_ACK_DEADLINE_MINUTES)
    )
    just_past = acknowledgement_status(
        _ROUTED, _ROUTED + timedelta(minutes=DEFAULT_ACK_DEADLINE_MINUTES + 1)
    )
    assert just_inside.state is AckState.PENDING
    assert just_past.state is AckState.BREACHED


def test_now_before_routed_is_refused() -> None:
    with pytest.raises(FeedContractError):
        acknowledgement_status(_ROUTED, _ROUTED - timedelta(minutes=1))
