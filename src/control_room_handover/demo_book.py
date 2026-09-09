"""The shipped demo book: fictional ops-worklist exports, served the same way on both sides.

The rows live as newline-delimited JSON under ``control_room_handover/data/demo_book/``, one file
per BigQuery export table and in that table's column order, so one set of files feeds the DuckDB
store the offline profiles read, the loader that fills the managed dataset, and the tests. The
reading, the overwrite guard and the tenant rule come from :mod:`hex_service_kit.demobook`; what
is here is about THIS system.

**The window was measured from a wall clock, and the request's own date was thrown away.**
``HandoverRequest`` carries ``as_of`` and ``lookback_days``; the service passed only the lookback
to the port, and the managed adapter filled the gap with
``as_of >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback DAY)``. Three consequences, none visible to
a green offline gate, because the offline adapter took the last N ROWS of a file and never looked
at a date at all:

* a handover written for any date but today read the wrong window while reporting the requested
  one in its own heading, which is the shape of error a scorecard cannot survive;
* ``domain/acknowledgement.py`` states that the as-of and the sign-off time are inputs and never
  a wall clock read here. The managed adapter read one;
* this book is pinned to 2026-08-07, so on a deployment the query would have returned NOTHING and
  the handover pack would have been empty with nothing red anywhere. A fictional warehouse must
  be windowed from its own as-of date, never from today's, or the demo empties itself as it ages.

The port takes ``as_of`` now and both adapters window on it, so the offline gate stays byte
identical, a demo on the deployment asks for the book's own date, and production asks for today's.

**The dataset was hardcoded.** ``_TABLES`` named ``ops_worklist.<table>`` in the module, while
the comment above it said a deployment overrides the dataset via settings. There was no such
setting. There is now.

Everything is fictional. See ``data/demo_book/README.md``.
"""

from __future__ import annotations

from hex_service_kit.demobook import BookError, NdjsonBook, Table

from .domain.models import AGING_BUCKET_LABELS, FeedId

#: The tenant the manifest records. The export rows carry none: an ops worklist is this
#: deployment's own backlog, not a customer record, so there is no per-row data tag to stamp.
SHIPPED_TENANT = "demo-bank"
CROSS_TENANT: dict[str, str] = {}

#: The DuckDB struct that mirrors the BigQuery RECORD the export publishes. Written from the
#: labels the domain declares, so adding a bucket cannot leave the store a column short.
_AGING_STRUCT = "STRUCT(" + ", ".join(f'"{label}" BIGINT' for label in AGING_BUCKET_LABELS) + ")"
_SLA_STRUCT = "STRUCT(within BIGINT, due_soon BIGINT, breached BIGINT)"
_SOURCE_STRUCT = "STRUCT(feed VARCHAR, partition VARCHAR)"

#: The columns of every export table. The two feeds publish ONE contract, which is the point of
#: the shared row parser: F2 conforms to the shape F1 defined, so a third feed is a table and a
#: member rather than a second parse.
_EXPORT_COLUMNS = ("feed_id", "as_of", "queue_depth", "aging", "sla", "throughput", "source")
_EXPORT_TYPES = {
    "feed_id": "TEXT NOT NULL",
    # ISO 8601 text, matching the export contract and the domain model, so the two stores order
    # and window on the same value with no timezone conversion sitting between them.
    "as_of": "TEXT NOT NULL",
    "queue_depth": "BIGINT NOT NULL",
    "aging": _AGING_STRUCT,
    "sla": _SLA_STRUCT,
    "throughput": "BIGINT NOT NULL",
    "source": _SOURCE_STRUCT,
}


def _export_table(name: str) -> Table:
    return Table(
        name=name,
        columns=_EXPORT_COLUMNS,
        types=_EXPORT_TYPES,
        primary_key=("feed_id", "as_of"),
    )


RECON_BREAKS_EXPORT = _export_table("recon_breaks_export")
DISPUTES_EXPORT = _export_table("disputes_export")

#: Which export table each registered feed is read from, on BOTH sides. One map, so the local
#: store and the warehouse cannot disagree about where a feed's rows live.
TABLE_FOR_FEED: dict[FeedId, str] = {
    FeedId.RECON_BREAKS: RECON_BREAKS_EXPORT.name,
    FeedId.DISPUTES: DISPUTES_EXPORT.name,
}

TABLES = (RECON_BREAKS_EXPORT, DISPUTES_EXPORT)

BOOK = NdjsonBook("control_room_handover.data.demo_book", TABLES)


def book_as_of() -> str:
    """The date the book is written against: the newest snapshot it ships.

    A demo on the deployment asks for THIS date rather than today's. The alternative, rebasing
    the rows onto the load date, would make the loaded book differ from the shipped one and put
    the two stores back out of step, which is the state this whole change exists to leave.
    """
    return str(BOOK.manifest()["as_of_date"])


def validate() -> None:
    """The book's own invariants, on top of the shape the kit checks.

    The date rules are the load-bearing ones. A scorecard is a comparison across a window, so a
    duplicated date double-counts a day, a gap makes a trend read steeper than it was, and a
    manifest whose as-of is not the newest row is a book whose own demo asks for the wrong day.
    """
    BOOK.validate()
    declared_as_of = str(BOOK.manifest()["as_of_date"])
    newest: list[str] = []

    for table in TABLES:
        rows = BOOK.rows(table.name)
        if len(rows) < 2:
            raise BookError(
                f"{table.name} ships {len(rows)} rows; a scorecard compares across a window and "
                "cannot be computed from one snapshot"
            )
        dates = [str(row["as_of"]) for row in rows]
        if len(set(dates)) != len(dates):
            raise BookError(
                f"{table.name} ships two snapshots for one date; a day is counted twice"
            )
        newest.append(max(dates))

        feeds = {str(row["feed_id"]) for row in rows}
        if len(feeds) != 1:
            raise BookError(f"{table.name} mixes feeds {sorted(feeds)}; one export, one feed")
        feed = feeds.pop()
        if feed not in {f.value for f in FeedId}:
            raise BookError(f"{table.name} names an unregistered feed {feed!r}")

        for row in rows:
            where = f"{table.name}/{row['as_of']}"
            aging = row["aging"]
            if not isinstance(aging, dict) or set(aging) != set(AGING_BUCKET_LABELS):
                raise BookError(
                    f"{where} does not carry every aging bucket: a missing bucket is silently "
                    f"dropped by the parser and the backlog reads short. Expected "
                    f"{list(AGING_BUCKET_LABELS)}"
                )
            if sum(int(count) for count in aging.values()) != int(row["queue_depth"]):
                raise BookError(
                    f"{where} has aging buckets that do not sum to its queue depth, so the "
                    "backlog and its age profile describe different queues"
                )
            sla = row["sla"]
            if sum(int(sla[key]) for key in ("within", "due_soon", "breached")) != int(
                row["queue_depth"]
            ):
                raise BookError(
                    f"{where} has SLA states that do not sum to its queue depth, so an item is "
                    "either in two states or in none"
                )
            if int(row["throughput"]) < 0 or int(row["queue_depth"]) < 0:
                raise BookError(f"{where} has a negative count")

    if declared_as_of != max(newest):
        raise BookError(
            f"the manifest says the book is as of {declared_as_of!r} and its newest snapshot is "
            f"{max(newest)!r}. A demo asks the deployment for the manifest's date, so these "
            "disagreeing is a handover that reads an empty window."
        )
