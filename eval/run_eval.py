#!/usr/bin/env python3
"""Evaluation gate for Control Room Handover (F5).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change: it drives the real
  ``HandoverService`` against a golden set with SDK-free local adapters and scores three metrics,
  each against the DATASET'S OWN expected outcome (an independent golden oracle), never the
  pipeline's own verdict. Before scoring it PROVES every metric can go red
  (``agent_eval_kit.assert_each_can_go_red``): a metric that cannot fail is not a metric.
* **gate** - the promotion verdict from the shared Hrz4 authority (requires the ``gcp`` profile),
  via ``agent_eval_kit.PromotionGateClient``.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from agent_eval_kit import (
    EvalMetricResult,
    EvalReport,
    PromotionGateClient,
    assert_each_can_go_red,
    eval_main,
)
from pii_kit import pack_leak, redact

from control_room_handover.config import (
    Settings,
    build_container,
)
from control_room_handover.domain.handover_service import (
    HandoverService,
)
from control_room_handover.domain.models import (
    HandoverBrief,
    HandoverRequest,
)
from control_room_handover.domain.pii import (
    PII_PATTERNS,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"

THRESHOLDS: dict[str, float] = {
    "scorecard_accuracy": 1.0,
    "groundedness": 0.99,
    "pii_safety": 0.99,
}
#: The registered Hrz4 metric bundle for this vertical (Hrz4 owns the metrics + thresholds).
_BUNDLE = "control-room-handover"

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

#: A planted identifier for the pii_safety red-proof; obviously synthetic.
_PLANTED = "S1234567D"
_RAW = f"recon break tied to NRIC {_PLANTED} on file"


def _load(path: Path) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def _mean(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def _service() -> tuple[HandoverService, object]:
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = HandoverService(
        ops_feeds=container.ops_feeds,
        generation=container.generation,
        audit=container.audit,
        tts=container.tts,
        tracer=container.tracer,
    )
    return service, container.audit


# --------------------------------------------------------------------------------------- #
# Single-argument scorers, so the same functions score the smoke run AND prove they go red.
# --------------------------------------------------------------------------------------- #
def _scorecard_score(pair: tuple[dict[str, object], dict[str, object]]) -> float:
    """1.0 iff the engine's totals and per-feed severities match the independent oracle."""
    actual, expected = pair
    if actual.get("total_queue_depth") != expected.get("expected_total_queue"):
        return 0.0
    if actual.get("total_sla_breached") != expected.get("expected_total_breached"):
        return 0.0
    if actual.get("overall_severity") != expected.get("expected_overall_severity"):
        return 0.0
    if actual.get("feed_severity") != expected.get("expected_feed_severity"):
        return 0.0
    return 1.0


def _groundedness_score(pair: tuple[str, frozenset[str]]) -> float:
    """1.0 iff every number in the narration appears in the engine evidence (no invented figure)."""
    summary, allowed = pair
    return 0.0 if any(tok not in allowed for tok in _NUMBER_RE.findall(summary)) else 1.0


def _pii_score(text: str) -> float:
    """1.0 unless a raw identifier (per the shared pack) survives into ``text``."""
    return 0.0 if pack_leak(text, PII_PATTERNS) else 1.0


def _brief_facts(brief: HandoverBrief) -> dict[str, object]:
    card = brief.scorecard
    return {
        "total_queue_depth": card.total_queue_depth,
        "total_sla_breached": card.total_sla_breached,
        "overall_severity": card.overall_severity.value,
        "feed_severity": {f.feed_id.value: f.severity.value for f in card.feeds},
    }


def _engine_numbers(brief: HandoverBrief) -> frozenset[str]:
    card = brief.scorecard
    tokens: set[str] = set()
    parts = [str(card.total_queue_depth), str(card.total_sla_breached), card.as_of]
    for feed in card.feeds:
        parts += [
            str(feed.queue_depth),
            str(feed.sla_breached),
            str(feed.throughput),
            str(feed.drain_ratio),
            str(feed.capacity),
        ]
    for part in parts:
        tokens.update(_NUMBER_RE.findall(part))
    return frozenset(tokens)


def _prove_metrics_can_go_red() -> None:
    """Every metric must be provable able to FAIL, per segment, before it is trusted green."""
    assert_each_can_go_red(
        _pii_score,
        {"universal": (redact(_RAW, PII_PATTERNS), _RAW)},
        threshold=THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )
    assert_each_can_go_red(
        _groundedness_score,
        {"narration": (("backlog computed", frozenset()), ("backlog is 999 items", frozenset()))},
        threshold=THRESHOLDS["groundedness"],
        metric="groundedness",
    )
    good = ({"total_queue_depth": 1}, {"expected_total_queue": 1})
    bad = ({"total_queue_depth": 2}, {"expected_total_queue": 1})
    assert_each_can_go_red(
        _scorecard_score,
        {"totals": (good, bad)},
        threshold=THRESHOLDS["scorecard_accuracy"],
        metric="scorecard_accuracy",
    )


def run_smoke(dataset: Path) -> EvalReport:
    _prove_metrics_can_go_red()
    cases = _load(dataset)
    service, audit = _service()

    scorecard_scores: list[float] = []
    grounded_scores: list[float] = []
    pii_scores: list[float] = []

    for case in cases:
        request = HandoverRequest(
            shift_id=str(case["shift_id"]),
            as_of=str(case["as_of"]),
            lookback_days=int(case["lookback_days"]),  # type: ignore[arg-type]
        )
        brief = service.build_handover(request, actor="eval-bot")
        scorecard_scores.append(_scorecard_score((_brief_facts(brief), case)))
        grounded_scores.append(_groundedness_score((brief.summary, _engine_numbers(brief))))
        # The audit record and the narration must carry no raw identifier.
        pii_scores.append(_pii_score(brief.summary + " " + brief.subject))

    # An independent record-level scan too, so pii_safety is not just the summary's word.
    records = [str(e.get("redacted_summary", "")) for e in audit.log.read_all()]  # type: ignore[attr-defined]
    if any(pack_leak(text, PII_PATTERNS) for text in records):
        pii_scores.append(0.0)

    results = (
        EvalMetricResult.scored(
            "scorecard_accuracy", _mean(scorecard_scores), THRESHOLDS["scorecard_accuracy"]
        ),
        EvalMetricResult.scored("groundedness", _mean(grounded_scores), THRESHOLDS["groundedness"]),
        EvalMetricResult.scored("pii_safety", _mean(pii_scores), THRESHOLDS["pii_safety"]),
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(cases))


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"CONTROLROOM_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("CONTROLROOM_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / Hrz4 evaluation gate for F5.",
        )
    )
