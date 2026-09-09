"""Drift guard: every shipped export row conforms to the consumed contract.

F5 consumes the ops-worklist export F1 publishes and F2 conforms to. This repo holds a CONSUMED
copy of the schema (``schema/ops_worklist_export.schema.json``) because F1 is not present in this
wave; the assumption is recorded in ``docs/ops-metrics-contract.md``. This suite validates every
shipped row against that schema, so a row that stopped conforming, or a schema that drifted from
the rows, fails the build rather than the feed reader failing at run time. It also proves the feed
port fails CLOSED on an unknown feed and a malformed row.

The rows validated are the demo book's (``src/control_room_handover/data/demo_book/``), which is
what BOTH stores now serve: the DuckDB store the offline profiles read and the BigQuery tables
the loader fills. They used to be a separate ``fixtures/ops_worklist/`` directory that only the
offline adapter read, so this guard held the contract against rows the deployment never saw.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from control_room_handover import demo_book
from control_room_handover.adapters._feed_parser import snapshot_from_export_row
from control_room_handover.adapters.local.ops_feeds import LocalOpsFeedAdapter
from control_room_handover.config import Settings
from control_room_handover.domain.errors import FeedContractError, UnknownFeedError
from control_room_handover.domain.models import FeedId

from tests import REPO_ROOT

_SCHEMA = json.loads(
    (REPO_ROOT / "schema" / "ops_worklist_export.schema.json").read_text(encoding="utf-8")
)
_EXPORT_TABLES = [table.name for table in demo_book.TABLES]


def test_there_are_rows_to_validate() -> None:
    assert _EXPORT_TABLES, "the book ships no export tables; the drift guard would be vacuous"


@pytest.mark.parametrize("table", _EXPORT_TABLES)
def test_every_shipped_row_conforms_to_the_consumed_contract(table: str) -> None:
    rows = demo_book.BOOK.rows(table)
    assert rows, f"{table} is empty"
    for row in rows:
        jsonschema.validate(row, _SCHEMA)
        # And it must parse into a validated domain snapshot without loss.
        snapshot_from_export_row(row)


def test_the_registry_lists_exactly_the_two_wave_feeds() -> None:
    adapter = LocalOpsFeedAdapter(Settings(profile="local"))
    assert set(adapter.feeds()) == {FeedId.RECON_BREAKS, FeedId.DISPUTES}


def test_an_unknown_feed_fails_closed() -> None:
    with pytest.raises(UnknownFeedError):
        snapshot_from_export_row(
            {
                "feed_id": "not_a_feed",
                "as_of": "2026-08-07",
                "queue_depth": 1,
                "aging": {"0-1d": 1, "1-3d": 0, "3-7d": 0, "7d+": 0},
                "sla": {"within": 1, "due_soon": 0, "breached": 0},
                "throughput": 0,
                "source": {"feed": "x", "partition": "y"},
            }
        )


def test_a_row_missing_a_required_field_fails_closed() -> None:
    with pytest.raises(FeedContractError):
        snapshot_from_export_row({"feed_id": "recon_breaks", "as_of": "2026-08-07"})
