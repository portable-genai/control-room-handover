"""ScorecardEngine: the deterministic control-room scorecard over the ops-feed snapshots.

The product is this engine, not the narration. Cribbed from performance-marketing-optimisation's
``efficiency_service`` (pure, division-guarded ratios) and its ``anomaly_service`` (robust-z, here
in ``anomaly.py``): given the raw cited feed snapshots and the staffing baselines it computes, per
feed, the queue depth, the backlog aging profile, the SLA breach count and rate, the throughput, the
drain ratio (throughput / queue depth), the capacity utilisation against the configured baseline and
the capacity call-out, then rolls the feeds up into a control-room scorecard. Every number is owned
here; the LLM narrates them and produces none.

Determinism: same snapshots + same baselines + same ``as_of`` -> same scorecard. No clock read,
no randomness, no network, guarded division everywhere, stable ordering.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .anomaly import AnomalyEngine
from .kernel import Citation, Severity
from .models import (
    AgingBucket,
    AnomalyFinding,
    ControlRoomScorecard,
    FeedId,
    FeedScorecard,
    FeedSnapshot,
    StaffingBaseline,
)

#: Severity bands for a feed's SLA breach rate. Ordered by ascending floor; the highest floor a
#: rate clears wins. Policy config in spirit (a follow-up lifts these into ``settings.yaml``); the
#: defaults are obviously illustrative, not a client's numbers.
_BREACH_RATE_BANDS: tuple[tuple[float, Severity], ...] = (
    (0.20, Severity.CRITICAL),
    (0.10, Severity.HIGH),
    (0.02, Severity.MEDIUM),
)

_SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
)


@dataclass(frozen=True, slots=True)
class ScorecardEngine:
    """Pure, deterministic control-room scorecard computation."""

    anomaly: AnomalyEngine = AnomalyEngine()

    def compute(
        self,
        as_of: str,
        series_by_feed: dict[FeedId, tuple[FeedSnapshot, ...]],
        baselines: dict[FeedId, StaffingBaseline],
    ) -> ControlRoomScorecard:
        """Score every feed present in ``series_by_feed`` and roll them up. Stable feed order."""
        feed_cards: list[FeedScorecard] = []
        for feed_id in sorted(series_by_feed, key=lambda f: f.value):
            series = series_by_feed[feed_id]
            if not series:
                continue
            feed_cards.append(self._score_feed(feed_id, series, baselines.get(feed_id)))

        total_queue = sum(card.queue_depth for card in feed_cards)
        total_breached = sum(card.sla_breached for card in feed_cards)
        overall = self._max_severity(card.severity for card in feed_cards)
        citations = self._dedupe(cit for card in feed_cards for cit in card.citations)
        return ControlRoomScorecard(
            as_of=as_of,
            feeds=tuple(feed_cards),
            total_queue_depth=total_queue,
            total_sla_breached=total_breached,
            overall_severity=overall,
            citations=citations,
        )

    def _score_feed(
        self,
        feed_id: FeedId,
        series: tuple[FeedSnapshot, ...],
        baseline: StaffingBaseline | None,
    ) -> FeedScorecard:
        current = max(series, key=lambda s: s.as_of)
        breach_rate = self._safe_div(current.sla_breached, current.sla_total)
        drain_ratio = self._safe_div(current.throughput, current.queue_depth)
        capacity = baseline.capacity if baseline is not None else 0
        utilisation = self._safe_div(current.queue_depth, capacity)
        capacity_callout = capacity > 0 and current.queue_depth > capacity
        anomalies = self.anomaly.detect(feed_id, series)
        severity = self._feed_severity(breach_rate, capacity_callout, anomalies)
        citations = self._dedupe(
            [current.citation, *(cit for a in anomalies for cit in a.citations)]
        )
        return FeedScorecard(
            feed_id=feed_id,
            as_of=current.as_of,
            queue_depth=current.queue_depth,
            aging=self._normalise_aging(current.aging),
            sla_breached=current.sla_breached,
            sla_breach_rate=round(breach_rate, 6),
            throughput=current.throughput,
            drain_ratio=round(drain_ratio, 6),
            capacity=capacity,
            capacity_utilisation=round(utilisation, 6),
            capacity_callout=capacity_callout,
            severity=severity,
            anomalies=anomalies,
            citations=citations,
        )

    # ------------------------------------------------------------------ severity
    def _feed_severity(
        self,
        breach_rate: float,
        capacity_callout: bool,
        anomalies: tuple[AnomalyFinding, ...],
    ) -> Severity:
        severity = Severity.LOW
        for floor, band in _BREACH_RATE_BANDS:
            if breach_rate >= floor:
                severity = band
                break
        if capacity_callout:
            severity = self._max_severity((severity, Severity.HIGH))
        if anomalies:
            severity = self._max_severity((severity, *(a.severity for a in anomalies)))
        return severity

    @classmethod
    def _max_severity(cls, severities: Iterable[Severity]) -> Severity:
        present = list(severities)
        if not present:
            return Severity.LOW
        return max(present, key=lambda s: _SEVERITY_ORDER.index(s))

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _safe_div(numerator: float, denominator: float) -> float:
        return numerator / denominator if denominator > 0 else 0.0

    @staticmethod
    def _normalise_aging(aging: tuple[AgingBucket, ...]) -> tuple[AgingBucket, ...]:
        # The snapshot already validated label set and order; re-emit as-is for a stable card.
        return tuple(aging)

    @staticmethod
    def _dedupe(citations: Iterable[Citation]) -> tuple[Citation, ...]:
        seen: set[tuple[str, str]] = set()
        out: list[Citation] = []
        for cit in citations:
            key = (cit.source_id, cit.snippet)
            if key not in seen:
                seen.add(key)
                out.append(cit)
        return tuple(out)
