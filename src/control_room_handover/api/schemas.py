"""API request/response schemas (Pydantic) mapped to/from the pure-domain models."""

from __future__ import annotations

from pydantic import BaseModel

from ..domain.models import HandoverBrief


class HandoverRequest(BaseModel):
    shift_id: str
    as_of: str
    lookback_days: int = 14


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class AgingBucketModel(BaseModel):
    label: str
    count: int


class FeedScorecardModel(BaseModel):
    feed_id: str
    as_of: str
    queue_depth: int
    aging: list[AgingBucketModel]
    sla_breached: int
    sla_breach_rate: float
    throughput: int
    drain_ratio: float
    capacity: int
    capacity_utilisation: float
    capacity_callout: bool
    severity: str
    anomaly_count: int


class HandoverResponse(BaseModel):
    subject: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    #: True when the model narration passed schema + grounding checks; False when it was
    #: discarded and the deterministic summary was used instead. Either way the numbers are the
    #: engine's, so a discarded narration degrades the prose, never the figures.
    narration_grounded: bool
    #: Where the handover WENT for the incoming lead's sign-off (rule R8): the human-review-console
    #: review id or
    #: the local queue reference. Never empty, because a handover always routes for acknowledgement.
    review_ref: str = ""
    voice_ref: str = ""
    as_of: str = ""
    total_queue_depth: int = 0
    total_sla_breached: int = 0
    feeds: list[FeedScorecardModel] = []
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(cls, brief: HandoverBrief, *, review_ref: str = "") -> HandoverResponse:
        scorecard = brief.scorecard
        return cls(
            subject=brief.subject,
            severity=brief.severity.value,
            decision=brief.decision.value,
            summary=brief.summary,
            requires_human_review=brief.requires_human_review,
            narration_grounded=brief.narration_grounded,
            review_ref=review_ref,
            voice_ref=brief.voice_ref,
            as_of=scorecard.as_of,
            total_queue_depth=scorecard.total_queue_depth,
            total_sla_breached=scorecard.total_sla_breached,
            feeds=[
                FeedScorecardModel(
                    feed_id=card.feed_id.value,
                    as_of=card.as_of,
                    queue_depth=card.queue_depth,
                    aging=[AgingBucketModel(label=b.label, count=b.count) for b in card.aging],
                    sla_breached=card.sla_breached,
                    sla_breach_rate=card.sla_breach_rate,
                    throughput=card.throughput,
                    drain_ratio=card.drain_ratio,
                    capacity=card.capacity,
                    capacity_utilisation=card.capacity_utilisation,
                    capacity_callout=card.capacity_callout,
                    severity=card.severity.value,
                    anomaly_count=len(card.anomalies),
                )
                for card in scorecard.feeds
            ],
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in brief.citations
            ],
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str
    #: Provenance the UI banner states on every page: where the runtime sits and which model
    #: answers. Both are read off the service because the browser cannot know either.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"
