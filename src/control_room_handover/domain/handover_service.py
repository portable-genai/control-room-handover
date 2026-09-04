"""HandoverService: the control-room shift-handover orchestrator (performance-marketing-optimisation
report_service shape).

Owns the whole pipeline and calls only ports plus the deterministic engine. The
:class:`ScorecardEngine` decides everything consequential (every queue depth, breach count, drain
ratio, capacity call-out and severity); the LLM only narrates the already-computed scorecard, and
its narration is schema-validated and grounding-checked and DISCARDED for a deterministic summary on
any failure, so a number the engine never produced can never reach a brief. Personal data is
redacted before the model sees the evidence and before the audit write. A handover always requires
the incoming shift lead's sign-off, so the brief is routed to human-review-console for
acknowledgement (rule R8).

Pure domain code: no cloud SDK, no web framework, no ADK. It takes its ports explicitly.
"""

from __future__ import annotations

import json
import re

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.generation import GenerationPort
from ..ports.observability import ObservabilityTracerPort
from ..ports.ops_feeds import OpsFeedPort
from ..ports.tts import SpeechSynthesisRequest, TextToSpeechPort
from .errors import FeedsEmptyError, NarrationDiscardedError
from .kernel import AuditEvent, Citation, Decision, Severity, utcnow
from .models import (
    ControlRoomScorecard,
    FeedId,
    FeedScorecard,
    FeedSnapshot,
    HandoverBrief,
    HandoverRequest,
    LlmMessage,
    LlmRequest,
    StaffingBaseline,
)
from .pii import PII_PATTERNS
from .policy import DEFAULT_STAFFING
from .scorecard_engine import ScorecardEngine

_NARRATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "used_source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}

#: Any run of digits (optionally with a decimal point) in the narration. Every one must appear in
#: the engine evidence, or the narration invented a figure and is discarded.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

#: One span per handover built. Structural attributes only: see
#: :meth:`HandoverService.build_handover`.
_HANDOVER_SPAN = "handover.build"


class HandoverService:
    """Build a cited, reviewed shift-handover brief. Constructor takes explicit ports."""

    def __init__(
        self,
        ops_feeds: OpsFeedPort,
        generation: GenerationPort,
        audit: AuditSinkPort,
        tts: TextToSpeechPort | None = None,
        *,
        tracer: ObservabilityTracerPort,
        baselines: dict[FeedId, StaffingBaseline] | None = None,
        engine: ScorecardEngine | None = None,
    ) -> None:
        self._ops_feeds = ops_feeds
        self._generation = generation
        self._audit = audit
        self._tts = tts
        self._tracer = tracer
        self._baselines = baselines or DEFAULT_STAFFING
        self._engine = engine or ScorecardEngine()

    # ------------------------------------------------------------------ public
    def build_handover(self, request: HandoverRequest, *, actor: str) -> HandoverBrief:
        """Read the feeds, score them deterministically, and narrate the scorecard.

        Routing the brief for the incoming lead's acknowledgement (rule R8) is the caller's step,
        in the same call that produced the brief, so the routing reference is captured where the
        surface can return it. ``requires_human_review`` is always True: a handover is not done
        until it is acknowledged.

        The whole path runs inside one span, whose attributes are a fixed structural set: the
        action and the actor, and nothing else. The caller-supplied ``shift_id`` and ``as_of``
        stay OFF the span deliberately: both arrive from the request body, so a caller can put
        anything in them, and the guard proves they stay off. Never a queue figure, never a
        citation snippet, never the narrated summary. A trace backend is not the WORM audit
        trail: it has no redaction stage, a wider read audience and no retention rule written
        against a regulator's requirement, so anything content-shaped that reaches a span has
        left the boundary the redact calls exist to hold, and left it silently.
        """
        with self._tracer.span(_HANDOVER_SPAN, action="build_handover", actor=actor):
            series_by_feed = self._read_feeds(request)
            if not any(series_by_feed.values()):
                raise FeedsEmptyError(
                    "no ops-feed snapshots available for the requested window; a handover brief "
                    "must be grounded in the F1 / F2 exports"
                )
            scorecard = self._engine.compute(request.as_of, series_by_feed, self._baselines)

            summary, grounded = self._narrate(scorecard)
            subject = f"Shift handover {request.shift_id} as of {request.as_of}"
            # A handover always goes to the incoming lead for sign-off.
            decision = Decision.ESCALATED
            brief = HandoverBrief(
                subject=subject,
                severity=scorecard.overall_severity,
                decision=decision,
                summary=summary,
                requires_human_review=True,
                scorecard=scorecard,
                narration_grounded=grounded,
                voice_ref=self._synthesize(subject, summary),
                citations=scorecard.citations,
            )
            self._record(brief, actor)
            return brief

    # ------------------------------------------------------------------ feeds
    def _read_feeds(self, request: HandoverRequest) -> dict[FeedId, tuple[FeedSnapshot, ...]]:
        out: dict[FeedId, tuple[FeedSnapshot, ...]] = {}
        for feed_id in self._ops_feeds.feeds():
            out[feed_id] = self._ops_feeds.snapshots(feed_id, request.lookback_days)
        return out

    # ------------------------------------------------------------------ narration
    def _narrate(self, scorecard: ControlRoomScorecard) -> tuple[str, bool]:
        evidence, allowed_numbers = self._render_evidence(scorecard)
        prompt = (
            "Write a concise operations shift-handover narrative. Use ONLY the computed figures "
            "below and cite the source ids you used. Do not introduce any number that is not in "
            f"the figures.\n\nFIGURES:\n{redact(evidence, PII_PATTERNS)}"
        )
        request = LlmRequest(
            messages=(LlmMessage(role="user", content=prompt),),
            response_schema=_NARRATION_SCHEMA,
        )
        try:
            response = self._generation.generate(request)
            summary = self._extract_and_check(response.text, allowed_numbers)
        except NarrationDiscardedError:
            return self._fallback_summary(scorecard), False
        except Exception:  # noqa: BLE001 - a narrator failure must never fail the handover
            return self._fallback_summary(scorecard), False
        return summary, True

    def _extract_and_check(self, text: str, allowed_numbers: frozenset[str]) -> str:
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise NarrationDiscardedError("narration was not valid JSON") from exc
        raw_summary = obj.get("summary") if isinstance(obj, dict) else None
        if not isinstance(raw_summary, str):
            raise NarrationDiscardedError("narration did not match the required schema")
        summary = raw_summary.strip()
        if not summary:
            raise NarrationDiscardedError("narration summary was empty")
        for token in _NUMBER_RE.findall(summary):
            if token not in allowed_numbers:
                raise NarrationDiscardedError(
                    f"narration cited a figure {token!r} the engine never produced"
                )
        return summary

    @staticmethod
    def _render_evidence(scorecard: ControlRoomScorecard) -> tuple[str, frozenset[str]]:
        lines: list[str] = [
            f"as_of {scorecard.as_of}; total queue {scorecard.total_queue_depth}; "
            f"total SLA breached {scorecard.total_sla_breached}; "
            f"overall severity {scorecard.overall_severity.value}"
        ]
        numbers: set[str] = set()
        for card in scorecard.feeds:
            source = card.citations[0].source_id if card.citations else card.feed_id.value
            lines.append(
                f"[{source}] {card.feed_id.value}: queue {card.queue_depth}, "
                f"breached {card.sla_breached}, throughput {card.throughput}, "
                f"drain {card.drain_ratio}, capacity {card.capacity}"
            )
            for anomaly in card.anomalies:
                lines.append(
                    f"[{source}] anomaly {anomaly.metric} {anomaly.kind.value} "
                    f"z {anomaly.deviation}"
                )
        for token in _NUMBER_RE.findall(" ".join(lines)):
            numbers.add(token)
        return "\n".join(lines), frozenset(numbers)

    @staticmethod
    def _fallback_summary(scorecard: ControlRoomScorecard) -> str:
        return (
            f"Shift handover as of {scorecard.as_of}: total backlog "
            f"{scorecard.total_queue_depth} items across {len(scorecard.feeds)} feeds, "
            f"{scorecard.total_sla_breached} SLA breaches, overall severity "
            f"{scorecard.overall_severity.value}. Figures are engine-computed and cited; this "
            "handover requires the incoming shift lead's acknowledgement."
        )

    # ------------------------------------------------------------------ voice
    def _synthesize(self, subject: str, summary: str) -> str:
        if self._tts is None:
            return ""
        try:
            result = self._tts.synthesize(
                SpeechSynthesisRequest(
                    request_id=subject,
                    text=summary,
                    locale="en-SG",
                )
            )
        except Exception:  # noqa: BLE001 - voice is optional enrichment, never load-bearing
            return ""
        return result.audio.uri

    # ------------------------------------------------------------------ audit
    def _record(self, brief: HandoverBrief, actor: str) -> None:
        rendered = self._audit_summary(brief)
        self._audit.record(
            AuditEvent(
                action="shift_handover",
                actor=actor,
                decision=brief.decision,
                severity=brief.severity,
                redacted_summary=redact(rendered, PII_PATTERNS),
                citations=brief.citations,
                timestamp=utcnow(),
            )
        )

    @staticmethod
    def _audit_summary(brief: HandoverBrief) -> str:
        return f"{brief.subject} :: {brief.summary}"


def worst_feed(scorecard: ControlRoomScorecard) -> FeedScorecard | None:
    """The feed carrying the highest severity, then the deepest queue (a UI / narration helper)."""
    order: dict[Severity, int] = {
        Severity.LOW: 0,
        Severity.MEDIUM: 1,
        Severity.HIGH: 2,
        Severity.CRITICAL: 3,
    }
    if not scorecard.feeds:
        return None
    return max(scorecard.feeds, key=lambda c: (order[c.severity], c.queue_depth))


def collect_citations(cards: tuple[FeedScorecard, ...]) -> tuple[Citation, ...]:
    """De-duplicated citations across a set of feed cards (used by the API assembly)."""
    seen: set[tuple[str, str]] = set()
    out: list[Citation] = []
    for card in cards:
        for cit in card.citations:
            key = (cit.source_id, cit.snippet)
            if key not in seen:
                seen.add(key)
                out.append(cit)
    return tuple(out)
