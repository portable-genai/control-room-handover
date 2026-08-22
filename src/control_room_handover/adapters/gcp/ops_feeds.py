"""Managed OpsFeedPort: read the F1 / F2 export tables from BigQuery (SDK imported lazily).

The primary adapter. It queries the ops-worklist export tables that F1 (``ops-recon-breaks-
engine``) writes and F2 (``disputes-chargebacks-manager``) conforms to, one snapshot row per
feed per ``as_of``, and parses each row through the shared parser so it stays byte-identical with
the offline replay. The ``google.cloud.bigquery`` import is INSIDE the method, so the ``local``
and ``onprem`` profiles import this module with no BigQuery SDK installed. It returns raw cited
rows and computes nothing; the scorecard engine does.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.errors import UnknownFeedError
from ...domain.models import FeedId, FeedSnapshot
from .._feed_parser import snapshot_from_export_row

#: The export table each registered feed is read from. A deployment overrides the dataset via
#: settings; the feed set is fixed to the registered members so an unknown feed cannot be queried.
_TABLES: dict[FeedId, str] = {
    FeedId.RECON_BREAKS: "ops_worklist.recon_breaks_export",
    FeedId.DISPUTES: "ops_worklist.disputes_export",
}


class CloudOpsFeedAdapter:
    """BigQuery-backed ops-feed reader for the managed profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def feeds(self) -> tuple[FeedId, ...]:
        return tuple(sorted(_TABLES, key=lambda f: f.value))

    def snapshots(self, feed_id: FeedId, lookback_days: int) -> tuple[FeedSnapshot, ...]:
        table = _TABLES.get(feed_id)
        if table is None:
            raise UnknownFeedError(f"no export table for feed {feed_id.value!r}")
        rows = self._query(table, lookback_days)
        snapshots = [snapshot_from_export_row(row) for row in rows]
        snapshots.sort(key=lambda s: s.as_of)
        return tuple(snapshots)

    def _query(self, table: str, lookback_days: int) -> list[dict[str, Any]]:
        # Lazy import: the offline profiles must import this module with no BigQuery SDK present.
        from google.cloud import bigquery  # noqa: PLC0415

        client = bigquery.Client()
        sql = (
            f"SELECT feed_id, as_of, queue_depth, aging, sla, throughput, source "  # noqa: S608
            f"FROM `{table}` "
            "WHERE as_of >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback DAY) "
            "ORDER BY as_of ASC"
        )
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookback", "INT64", lookback_days),
            ]
        )
        return [dict(row) for row in client.query(sql, job_config=job_config).result()]
