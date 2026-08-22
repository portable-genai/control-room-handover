"""AnomalyEngine: deterministic robust-z spike / drop detection over a feed's snapshot series.

Pure, stdlib-only, replayable (the ``deterministic-domain-service`` skill). Given a dated series
of one feed's snapshots it flags a spike or a drop in queue depth or SLA breaches with a robust
z-score: the deviation from the median scaled by the median absolute deviation, which resists the
very outliers it is screening. An anomaly raises the feed's severity and is called out in the
handover; detection is therefore code an auditor can re-run, never an LLM hunch. The model only
narrates the anomaly the engine found.

Determinism: same series -> same output. No clock read inside the method, no randomness, no
network. The thresholds and the minimum window are tunable fields, not magic numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

from .kernel import Citation, Severity
from .models import AnomalyFinding, AnomalyKind, FeedId, FeedSnapshot

# 0.6745 is the 0.75 quantile of the standard normal; it scales MAD to a normal-consistent sigma.
_MAD_SCALE = 0.6745

#: The snapshot metrics screened for anomalies, each read from a snapshot as a float.
_METRICS: tuple[str, ...] = ("queue_depth", "sla_breached")


@dataclass(frozen=True, slots=True)
class AnomalyEngine:
    """Pure, deterministic robust-z anomaly detection over one feed's snapshot series."""

    z_threshold: float = 3.0
    high_threshold: float = 4.0
    critical_threshold: float = 6.0
    min_window: int = 4

    def detect(
        self, feed_id: FeedId, series: tuple[FeedSnapshot, ...] | list[FeedSnapshot]
    ) -> tuple[AnomalyFinding, ...]:
        """Flag a spike / drop in the LATEST snapshot of ``series`` for each screened metric."""
        ordered = sorted(series, key=lambda s: s.as_of)
        findings: list[AnomalyFinding] = []
        for metric in _METRICS:
            finding = self._detect_one(feed_id, metric, ordered)
            if finding is not None:
                findings.append(finding)
        findings.sort(key=lambda a: (-abs(a.deviation), a.metric))
        return tuple(findings)

    def _detect_one(
        self, feed_id: FeedId, metric: str, series: list[FeedSnapshot]
    ) -> AnomalyFinding | None:
        if len(series) < self.min_window + 1:
            return None
        baseline = [float(getattr(s, metric)) for s in series[:-1]]
        candidate = series[-1]
        value = float(getattr(candidate, metric))
        median = self._median(baseline)
        mad = self._mad(baseline, median)
        deviation = self._robust_z(value, median, mad)
        if abs(deviation) < self.z_threshold:
            return None
        kind = AnomalyKind.SPIKE if deviation > 0 else AnomalyKind.DROP
        return AnomalyFinding(
            feed_id=feed_id,
            metric=metric,
            observed_date=candidate.as_of,
            value=round(value, 6),
            baseline=round(median, 6),
            deviation=round(deviation, 6),
            kind=kind,
            severity=self._severity(abs(deviation)),
            rationale=(
                f"{metric} {kind.value}: {value:.2f} vs baseline {median:.2f} "
                f"(robust z {deviation:.2f})."
            ),
            citations=self._citations(candidate),
        )

    @staticmethod
    def _median(values: list[float]) -> float:
        ordered = sorted(values)
        n = len(ordered)
        if n == 0:
            return 0.0
        mid = n // 2
        if n % 2 == 1:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2.0

    def _mad(self, values: list[float], median: float) -> float:
        return self._median([abs(v - median) for v in values])

    def _robust_z(self, value: float, median: float, mad: float) -> float:
        if mad <= 0:
            # A degenerate window with no spread: only an exact match is non-anomalous.
            if value == median:
                return 0.0
            return (self.critical_threshold + 1.0) * (1.0 if value > median else -1.0)
        return _MAD_SCALE * (value - median) / mad

    def _severity(self, magnitude: float) -> Severity:
        if magnitude >= self.critical_threshold:
            return Severity.CRITICAL
        if magnitude >= self.high_threshold:
            return Severity.HIGH
        return Severity.MEDIUM

    @staticmethod
    def _citations(snapshot: FeedSnapshot) -> tuple[Citation, ...]:
        return (snapshot.citation,)
