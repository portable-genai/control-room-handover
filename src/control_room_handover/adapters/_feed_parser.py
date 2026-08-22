"""Shared parse from one ops-worklist export row to a :class:`FeedSnapshot`.

Lives in the adapter layer (not the pure domain) because it turns a wire-shaped export row, the
shape the BigQuery export and the golden fixtures both use, into the domain snapshot. Both the
managed BigQuery adapter and the offline fixture adapter go through here, so the two families
cannot drift on how a row becomes a snapshot. Fails closed: a row missing a field or naming an
unknown feed raises :class:`FeedContractError` rather than defaulting the value to zero.
"""

from __future__ import annotations

from typing import Any

from ..domain.errors import FeedContractError, UnknownFeedError
from ..domain.kernel import Citation
from ..domain.models import (
    AGING_BUCKET_LABELS,
    AgingBucket,
    FeedId,
    FeedSnapshot,
)


def _require(row: dict[str, Any], key: str) -> Any:
    if key not in row:
        raise FeedContractError(f"export row is missing required field {key!r}")
    return row[key]


def _feed_id(raw: object) -> FeedId:
    try:
        return FeedId(str(raw))
    except ValueError as exc:
        raise UnknownFeedError(f"export row names an unknown feed {raw!r}") from exc


def snapshot_from_export_row(row: dict[str, Any]) -> FeedSnapshot:
    """Build a validated :class:`FeedSnapshot` from one export row, or raise."""
    feed_id = _feed_id(_require(row, "feed_id"))
    aging_block = _require(row, "aging")
    if not isinstance(aging_block, dict):
        raise FeedContractError("export row 'aging' must be an object")
    aging = tuple(
        AgingBucket(label=label, count=int(aging_block[label]))
        for label in AGING_BUCKET_LABELS
        if label in aging_block
    )
    sla = _require(row, "sla")
    if not isinstance(sla, dict):
        raise FeedContractError("export row 'sla' must be an object")
    source = _require(row, "source")
    if not isinstance(source, dict):
        raise FeedContractError("export row 'source' must be an object")
    citation = Citation(
        source_id=str(_require(source, "feed")),
        title="Ops worklist export",
        snippet=str(_require(source, "partition")),
    )
    return FeedSnapshot(
        feed_id=feed_id,
        as_of=str(_require(row, "as_of")),
        queue_depth=int(_require(row, "queue_depth")),
        aging=aging,
        sla_within=int(_require(sla, "within")),
        sla_due_soon=int(_require(sla, "due_soon")),
        sla_breached=int(_require(sla, "breached")),
        throughput=int(_require(row, "throughput")),
        citation=citation,
    )
