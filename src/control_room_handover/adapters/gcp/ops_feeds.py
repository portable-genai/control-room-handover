"""Managed OpsFeedPort: read the F1 / F2 export tables from BigQuery (SDK imported lazily).

The primary adapter. It queries the ops-worklist export tables that F1 (``ops-recon-breaks-
engine``) writes and F2 (``disputes-chargebacks-manager``) conforms to, one snapshot row per
feed per ``as_of``, and parses each row through the shared parser so it stays byte-identical with
the offline replay. The ``google.cloud.bigquery`` import is INSIDE the method, so the ``local``
and ``onprem`` profiles import this module with no BigQuery SDK installed. It returns raw cited
rows and computes nothing; the scorecard engine does.

**The window ends at the request's own as-of, not at a wall clock.** This adapter used to filter
``as_of >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback DAY)`` while the service threw the
request's ``as_of`` away. A handover written for any date but today read the wrong window and
reported the requested one in its heading; a fictional book pinned to a date in the past returned
nothing at all; and ``domain/acknowledgement.py`` states that the as-of is an input and never a
clock read here. The offline adapter could not surface any of it, because it sliced the last N
rows of a file and never looked at a date.

**The dataset comes from settings.** It used to be hardcoded into ``_TABLES`` as
``ops_worklist.<table>``, directly under a comment claiming a deployment overrides it via
settings. There was no such setting.
"""

from __future__ import annotations

from typing import Any

from ... import demo_book
from ...config import Settings
from ...domain.errors import UnknownFeedError
from ...domain.models import FeedId, FeedSnapshot
from .._feed_parser import snapshot_from_export_row

#: The READ SET: every column this adapter names, in the SELECT list or the WHERE clause.
#: Declared rather than left implicit because a contract test holds it against the Terraform
#: that creates the tables, and a read set no test can see is one that drifts silently.
SELECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    table.name: table.columns for table in demo_book.TABLES
}

_SNAPSHOTS_SQL = """
SELECT {columns}
FROM `{table}`
WHERE as_of > DATE_SUB(DATE(@as_of), INTERVAL @lookback DAY) AND as_of <= DATE(@as_of)
ORDER BY as_of ASC
"""


class CloudOpsFeedAdapter:
    """BigQuery-backed ops-feed reader for the managed profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def feeds(self) -> tuple[FeedId, ...]:
        return tuple(sorted(demo_book.TABLE_FOR_FEED, key=lambda f: f.value))

    def snapshots(
        self, feed_id: FeedId, lookback_days: int, *, as_of: str
    ) -> tuple[FeedSnapshot, ...]:
        table = demo_book.TABLE_FOR_FEED.get(feed_id)
        if table is None:
            raise UnknownFeedError(f"no export table for feed {feed_id.value!r}")
        rows = self._query(table, lookback_days, as_of)
        snapshots = [snapshot_from_export_row(row) for row in rows]
        snapshots.sort(key=lambda s: s.as_of)
        return tuple(snapshots)

    def _dataset(self) -> str:
        dataset = self._settings.bigquery_dataset.strip()
        if not dataset:
            raise RuntimeError(
                "CONTROLROOM_BQ_DATASET is not configured, so the ops feed has no export tables "
                "to read. It refuses rather than returning an empty series: an empty series "
                "reads as a control room with nothing in its queues."
            )
        return dataset

    def _query(self, table: str, lookback_days: int, as_of: str) -> list[dict[str, Any]]:
        # The CONFIGURATION check runs before the SDK import, deliberately: an unconfigured
        # dataset is the more actionable of the two refusals, and an operator reading an
        # ImportError would go looking for a missing package rather than a missing variable.
        qualified = f"{self._dataset()}.{table}"
        # Lazy import: the offline profiles must import this module with no BigQuery SDK present.
        from google.cloud import bigquery  # noqa: PLC0415

        client = bigquery.Client(project=self._settings.project_id or None)
        sql = _SNAPSHOTS_SQL.format(columns=", ".join(SELECTED_COLUMNS[table]), table=qualified)
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookback", "INT64", lookback_days),
                bigquery.ScalarQueryParameter("as_of", "STRING", as_of),
            ]
        )
        return [dict(row) for row in client.query(sql, job_config=job_config).result()]
