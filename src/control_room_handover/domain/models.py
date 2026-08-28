"""Vertical artifact models: the ops feeds, the scorecard, and the shift-handover brief.

The artifacts THIS vertical produces, as opposed to the vertical-neutral machinery in
``kernel.py``. The service's own name is deliberately not substituted into this docstring: a
rendered line whose length depends on ``friendly_name`` fails the repo's own format check for
no reason but the length of its name.

Everything here is a frozen, validated dataclass. The feed snapshot is the RAW cited row an
ops-feed port returns (it computes nothing); the scorecard types are what the deterministic
engine produces over those rows; the handover brief is the reviewed artifact the shift lead
signs off. A fork building a different vertical rewrites this module and keeps ``kernel.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hex_service_kit.enums import LenientStrEnum

from .errors import FeedContractError
from .kernel import Citation, Decision, Severity


class FeedId(LenientStrEnum):
    """The ops worklist feeds F5 consumes. Exactly the two that exist in this wave.

    The registry lists these and only these; a snapshot naming anything else fails closed. F3
    and F4 are deferred, so a later feed joins here as one more member plus its fixture, never
    as new engine code.
    """

    RECON_BREAKS = "recon_breaks"  # F1 recon-breaks-engine worklist export
    DISPUTES = "disputes"  # F2 disputes-chargebacks-manager worklist export


class SlaClockState(LenientStrEnum):
    """The state of an item's regulatory / operational SLA clock, as the source feed reports it."""

    WITHIN = "within"  # comfortably inside the deadline
    DUE_SOON = "due_soon"  # inside the deadline but within the warning window
    BREACHED = "breached"  # past the deadline


class AnomalyKind(LenientStrEnum):
    SPIKE = "spike"
    DROP = "drop"


class AckState(LenientStrEnum):
    """Where a handover sits against its acknowledgement clock (slice 5)."""

    PENDING = "pending"  # routed, not yet signed off, still inside the window
    ACKNOWLEDGED = "acknowledged"  # the incoming shift lead signed off
    BREACHED = "breached"  # unacknowledged past the window


#: The canonical aging buckets, oldest last. A snapshot must carry exactly these labels in order,
#: so the scorecard and the heatmap mean the same thing across both feeds.
AGING_BUCKET_LABELS: tuple[str, ...] = ("0-1d", "1-3d", "3-7d", "7d+")


@dataclass(frozen=True, slots=True)
class AgingBucket:
    """One backlog-age bucket: a label from :data:`AGING_BUCKET_LABELS` and a non-negative count."""

    label: str
    count: int

    def __post_init__(self) -> None:
        if self.label not in AGING_BUCKET_LABELS:
            raise FeedContractError(f"unknown aging bucket label {self.label!r}")
        if self.count < 0:
            raise FeedContractError(f"aging bucket {self.label!r} count must be >= 0")


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    """One RAW, cited worklist snapshot from a feed at an ``as_of`` date.

    This is the ops-worklist export contract F1 publishes and F2 conforms to (see
    ``schema/ops_worklist_export.schema.json`` and ``docs/ops-metrics-contract.md``): feed id,
    queue depth, aging buckets, SLA-clock state counts, throughput and ``as_of``. The port that
    returns these NEVER computes a ratio or a verdict; the scorecard engine does. Every snapshot
    carries a citation naming the source feed and partition it was read from.
    """

    feed_id: FeedId
    as_of: str
    queue_depth: int
    aging: tuple[AgingBucket, ...]
    sla_within: int
    sla_due_soon: int
    sla_breached: int
    throughput: int
    citation: Citation

    def __post_init__(self) -> None:
        if not self.as_of.strip():
            raise FeedContractError("FeedSnapshot.as_of must be a non-empty ISO date")
        for name, value in (
            ("queue_depth", self.queue_depth),
            ("sla_within", self.sla_within),
            ("sla_due_soon", self.sla_due_soon),
            ("sla_breached", self.sla_breached),
            ("throughput", self.throughput),
        ):
            if value < 0:
                raise FeedContractError(f"FeedSnapshot.{name} must be >= 0, got {value}")
        labels = tuple(bucket.label for bucket in self.aging)
        if labels != AGING_BUCKET_LABELS:
            raise FeedContractError(
                f"FeedSnapshot.aging must carry exactly {AGING_BUCKET_LABELS} in order, "
                f"got {labels}"
            )

    @property
    def sla_total(self) -> int:
        """Items with a live SLA clock in any state (the breach-rate denominator)."""
        return self.sla_within + self.sla_due_soon + self.sla_breached


@dataclass(frozen=True, slots=True)
class StaffingBaseline:
    """Configured capacity for one feed: analysts on shift and items each can clear.

    Policy config, not a magic number in code: capacity is ``headcount * items_per_analyst``, and
    the scorecard calls out a feed whose queue exceeds it. A follow-up lifts these into a bank-
    owned ``policy:`` block; the defaults here are obviously synthetic.
    """

    feed_id: FeedId
    headcount: int
    items_per_analyst: int

    def __post_init__(self) -> None:
        if self.headcount < 0 or self.items_per_analyst < 0:
            raise FeedContractError("StaffingBaseline values must be >= 0")

    @property
    def capacity(self) -> int:
        return self.headcount * self.items_per_analyst


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    """A robust-z spike or drop the anomaly engine flagged in a feed's snapshot series."""

    feed_id: FeedId
    metric: str
    observed_date: str
    value: float
    baseline: float
    deviation: float
    kind: AnomalyKind
    severity: Severity
    rationale: str
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedScorecard:
    """The deterministic scorecard for ONE feed: every number engine-owned, all cited."""

    feed_id: FeedId
    as_of: str
    queue_depth: int
    aging: tuple[AgingBucket, ...]
    sla_breached: int
    sla_breach_rate: float
    throughput: int
    drain_ratio: float
    capacity: int
    capacity_utilisation: float
    capacity_callout: bool
    severity: Severity
    anomalies: tuple[AnomalyFinding, ...] = ()
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class ControlRoomScorecard:
    """The cross-feed control-room scorecard: per-feed cards plus the rolled-up totals."""

    as_of: str
    feeds: tuple[FeedScorecard, ...]
    total_queue_depth: int
    total_sla_breached: int
    overall_severity: Severity
    citations: tuple[Citation, ...] = ()


# --------------------------------------------------------------------------------------- #
# LLM narration types (the model narrates the scorecard; it never produces a number).
# --------------------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: str  # "user" | "model" | "system"
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[LlmMessage, ...]
    response_schema: dict[str, object] | None = None
    model: str | None = None
    temperature: float = 0.0  # omitted at a call site means this value; it must not sample
    max_output_tokens: int = 1024


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    model: str = ""


# --------------------------------------------------------------------------------------- #
# The request and the reviewed artifact.
# --------------------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class HandoverRequest:
    """One shift-handover ask: which shift, as of when, over how long a lookback window."""

    shift_id: str
    as_of: str
    lookback_days: int = 14

    def __post_init__(self) -> None:
        if not self.shift_id.strip():
            raise FeedContractError("HandoverRequest.shift_id must be non-empty")
        if not self.as_of.strip():
            raise FeedContractError("HandoverRequest.as_of must be a non-empty ISO date")
        if self.lookback_days < 1:
            raise FeedContractError("HandoverRequest.lookback_days must be >= 1")


@dataclass(frozen=True, slots=True)
class HandoverBrief:
    """The reviewed shift-handover brief: a narrated summary over an engine-owned scorecard.

    The consequential content (every queue depth, breach count, drain ratio and severity) comes
    from :class:`ControlRoomScorecard`, which the deterministic engine produced. ``summary`` is
    the model's narration OVER those numbers and adds none of its own. A handover always requires
    the incoming shift lead's sign-off, so ``requires_human_review`` is always True and the brief
    is routed for acknowledgement (rule R8). The R8 review plumbing reads ``subject``,
    ``severity``, ``decision``, ``summary``, ``requires_human_review`` and ``citations``.
    """

    subject: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    scorecard: ControlRoomScorecard
    narration_grounded: bool = True
    voice_ref: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class AcknowledgementStatus:
    """Where a routed handover sits against its acknowledgement clock (slice 5, deterministic)."""

    state: AckState
    minutes_elapsed: int
    deadline_minutes: int
    acknowledged_by: str = ""


@dataclass(frozen=True, slots=True)
class VoiceBrief:
    """A reference to a synthesised spoken handover, when a TTS adapter produced one."""

    uri: str
    media_type: str
    characters: int = 0
    fields: tuple[str, ...] = field(default_factory=tuple)
