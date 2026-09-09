"""Local OpsFeedPort: the shipped export book, in DuckDB, over the warehouse's own schema.

The ``local`` profile's copy of the BigQuery export tables. It used to read the fixture JSONL
files directly and return the last N ROWS, which is not the window the managed adapter reads:
that one filters on a DATE. Two stores that answer different questions from different data are
two stores nobody can compare, and it is why a managed adapter reading a wall clock, and a
service throwing the request's own as-of away, survived a green offline gate.

The store here holds the SAME tables in the SAME column order as ``infra/terraform/bigquery.tf``,
nested ``aging``, ``sla`` and ``source`` records included, and answers the SAME statement. Rows
still go through the shared parser, so the two families cannot drift on how a row becomes a
snapshot. No SDK, no network, reproducible: DuckDB is an embedded engine in a wheel.

The registry lists EXACTLY the two feeds that have tables; a request for anything else raises
rather than returning a quiet empty series.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit.demobook import DuckDbStore

from ... import demo_book
from ...config import Settings
from ...domain.errors import UnknownFeedError
from ...domain.models import FeedId, FeedSnapshot
from .._feed_parser import snapshot_from_export_row

#: The managed adapter's own statement, in DuckDB's dialect and parameter style. Kept beside it
#: on purpose: the two windows are the same window, measured from the same date.
_SNAPSHOTS_SQL = """
SELECT {columns}
FROM {table}
WHERE as_of > strftime(CAST(? AS DATE) - CAST(? AS INTEGER) * INTERVAL 1 DAY, '%Y-%m-%d')
  AND as_of <= ?
ORDER BY as_of ASC
"""


class LocalOpsFeedAdapter:
    """Serve the shipped export book from DuckDB for the SDK-free offline profiles."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store = DuckDbStore(demo_book.BOOK, settings.book_path)

    def feeds(self) -> tuple[FeedId, ...]:
        return tuple(sorted(demo_book.TABLE_FOR_FEED, key=lambda f: f.value))

    def snapshots(
        self, feed_id: FeedId, lookback_days: int, *, as_of: str
    ) -> tuple[FeedSnapshot, ...]:
        table = demo_book.TABLE_FOR_FEED.get(feed_id)
        if table is None:
            raise UnknownFeedError(f"no local table for feed {feed_id.value!r}")
        columns = demo_book.BOOK.table(table).columns
        sql = _SNAPSHOTS_SQL.format(columns=", ".join(columns), table=table)
        rows = self._store.connection.execute(sql, [as_of, lookback_days, as_of]).fetchall()
        snapshots = [snapshot_from_export_row(self._as_row(columns, row)) for row in rows]
        snapshots.sort(key=lambda s: s.as_of)
        return tuple(snapshots)

    def close(self) -> None:
        self._store.close()

    @staticmethod
    def _as_row(columns: tuple[str, ...], row: tuple[Any, ...]) -> dict[str, Any]:
        """One result tuple as the export row shape the shared parser reads.

        DuckDB returns a STRUCT as a dict, exactly as the BigQuery client returns a RECORD, so
        the nested ``aging``, ``sla`` and ``source`` blocks arrive in the same shape on both
        sides and the parser needs no branch for either.
        """
        return dict(zip(columns, row, strict=True))
