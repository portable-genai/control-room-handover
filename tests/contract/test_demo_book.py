"""The demo book: one export contract, served the same way on the laptop and the deployment.

Pinned here, and each was watched failing first:

* **the window was measured from a wall clock, and the request's own date was thrown away.**
  ``HandoverRequest`` carries ``as_of``; the service passed only ``lookback_days`` to the port,
  and the managed adapter filled the gap with ``DATE_SUB(CURRENT_DATE(), ...)``. A handover
  written for any date but today read the wrong window while its heading reported the requested
  one, ``domain/acknowledgement.py`` says the as-of is an input and never a clock read here, and
  this book, pinned to 2026-08-07, would have returned NOTHING on a deployment. Nothing offline
  could disagree: the local adapter took the last N ROWS of a file and never looked at a date;
* **the dataset did not exist, and was hardcoded anyway.** No file in ``infra/terraform/``
  created it, no API was enabled and no IAM role named BigQuery, while ``_TABLES`` named
  ``ops_worklist.<table>`` in the module under a comment saying a deployment overrides it via
  settings. There was no such setting;
* the adapter's read set is declared, every column in it is one the Terraform declares, and the
  book ships exactly those columns, nested records included;
* the set held against the Terraform is ``load_order()``, the set the LOADER writes.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from control_room_handover import demo_book
from control_room_handover.adapters.gcp import ops_feeds as managed
from control_room_handover.adapters.local.ops_feeds import LocalOpsFeedAdapter
from control_room_handover.config import Settings
from control_room_handover.domain.models import AGING_BUCKET_LABELS, FeedId

from tests import REPO_ROOT

_TF = REPO_ROOT / "infra" / "terraform" / "bigquery.tf"


def _settings() -> Settings:
    return dataclasses.replace(
        Settings.load(), profile="local", audit_path=":memory:", book_path=":memory:"
    )


@pytest.fixture
def feed() -> LocalOpsFeedAdapter:
    adapter = LocalOpsFeedAdapter(_settings())
    yield adapter
    adapter.close()


# --------------------------------------------------------------------------- #
# The shipped rows
# --------------------------------------------------------------------------- #
def test_the_shipped_book_is_internally_consistent() -> None:
    demo_book.validate()
    assert len(demo_book.BOOK.rows("recon_breaks_export")) == 8
    assert len(demo_book.BOOK.rows("disputes_export")) == 8
    assert demo_book.BOOK.manifest()["fictional"] is True
    assert demo_book.book_as_of() == "2026-08-07"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("queue_depth", 999, "aging buckets that do not sum"),
        ("aging", {"0-1d": 1}, "does not carry every aging bucket"),
        ("sla", {"within": 1, "due_soon": 0, "breached": 0}, "SLA states that do not sum"),
        ("throughput", -1, "negative count"),
    ],
)
def test_the_book_refuses_a_row_the_scorecard_could_not_compute(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object, message: str
) -> None:
    """Each is arithmetic the scorecard depends on and a hand edit breaks silently."""
    real = demo_book.BOOK.rows

    def broken(name: str):  # type: ignore[no-untyped-def]
        rows = real(name)
        if name != "recon_breaks_export":
            return rows
        return [dict(rows[0], **{field: value}), *rows[1:]]

    monkeypatch.setattr(demo_book.BOOK, "rows", broken)
    with pytest.raises(demo_book.BookError, match=message):
        demo_book.validate()


def test_a_manifest_that_disagrees_with_the_newest_snapshot_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A demo asks the deployment for the manifest's date; disagreeing is an empty window."""
    real = demo_book.BOOK.rows

    def stale(name: str):  # type: ignore[no-untyped-def]
        rows = real(name)
        if name != demo_book.BOOK.MANIFEST.name:
            return rows
        return [dict(rows[0], as_of_date="2026-01-01")]

    monkeypatch.setattr(demo_book.BOOK, "rows", stale)
    with pytest.raises(demo_book.BookError, match="newest snapshot"):
        demo_book.validate()


def test_two_snapshots_for_one_date_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scorecard compares across a window, so a duplicated date counts a day twice."""
    real = demo_book.BOOK.rows

    def duplicated(name: str):  # type: ignore[no-untyped-def]
        rows = real(name)
        return [rows[0], *rows] if name == "recon_breaks_export" else rows

    monkeypatch.setattr(demo_book.BOOK, "rows", duplicated)
    with pytest.raises(demo_book.BookError, match="one date"):
        demo_book.validate()


# --------------------------------------------------------------------------- #
# The managed schema, which did not exist
# --------------------------------------------------------------------------- #
def _terraform_tables() -> dict[str, set[str]]:
    assert _TF.exists(), (
        "infra/terraform/bigquery.tf is missing. The adapter queries two export tables; without "
        "this file nothing creates them and the managed profile fails at the first request."
    )
    text = _TF.read_text(encoding="utf-8")
    schemas = {
        name: set(re.findall(r'name\s*=\s*"([\w+-]+)"', body))
        for name, body in re.findall(
            r"(\w+)\s*=\s*jsonencode\(\[(.*?)\n  \]\)", text, flags=re.DOTALL
        )
    }
    blocks = re.findall(
        r'resource\s+"google_bigquery_table"\s+"\w+"\s*\{(.*?)\n\}', text, flags=re.DOTALL
    )
    assert blocks, "no google_bigquery_table blocks found; the regex or the file moved"
    out: dict[str, set[str]] = {}
    for block in blocks:
        table_id = re.search(r'table_id\s*=\s*"(\w+)"', block)
        assert table_id is not None
        inline = re.search(r"schema\s*=\s*jsonencode\(\[(.*?)\n  \]\)", block, flags=re.DOTALL)
        if inline is not None:
            out[table_id.group(1)] = set(re.findall(r'name\s*=\s*"([\w+-]+)"', inline.group(1)))
            continue
        shared = re.search(r"schema\s*=\s*local\.(\w+)", block)
        assert shared is not None, f"{table_id.group(1)} has no readable schema"
        out[table_id.group(1)] = schemas[shared.group(1)]
    return out


def test_the_dataset_the_settings_name_is_actually_created() -> None:
    """Nothing created it, no API enabled it, no IAM role named it, and no CMEK bound it."""
    text = _TF.read_text(encoding="utf-8")
    assert 'dataset_id  = "ops_worklist"' in text, "no google_bigquery_dataset creates it"
    apis = (REPO_ROOT / "infra" / "terraform" / "apis.tf").read_text(encoding="utf-8")
    assert '"bigquery.googleapis.com"' in apis, "the BigQuery API is not enabled"
    iam = (REPO_ROOT / "infra" / "terraform" / "iam.tf").read_text(encoding="utf-8")
    assert "roles/bigquery.dataViewer" in iam, "the serving identity cannot read the dataset"
    kms = (REPO_ROOT / "infra" / "terraform" / "kms.tf").read_text(encoding="utf-8")
    assert "bigquery-encryption.iam.gserviceaccount.com" in kms, (
        "no CMEK binding for BigQuery: the dataset would encrypt under Google-managed keys and "
        "look identical in the console"
    )


def test_the_managed_adapter_reads_only_columns_the_terraform_declares() -> None:
    declared = _terraform_tables()
    for table, columns in managed.SELECTED_COLUMNS.items():
        assert table in declared, f"{table!r} is not a Terraform table"
        undeclared = sorted(set(columns) - declared[table])
        assert not undeclared, f"{table} reads columns Terraform never declares: {undeclared}"


def test_the_book_and_the_terraform_declare_the_same_columns() -> None:
    """``load_order()``, so the manifest the loader writes is held too."""
    declared = _terraform_tables()
    for table in demo_book.BOOK.load_order():
        assert table.name in declared, f"the book ships {table.name} and Terraform does not"
        undeclared = sorted(set(table.columns) - declared[table.name])
        assert not undeclared, f"{table.name}: book columns Terraform lacks: {undeclared}"


def test_every_aging_bucket_the_domain_declares_is_in_the_schema() -> None:
    """The parser keeps only the labels it finds, so a missing bucket reads as a short backlog."""
    declared = _terraform_tables()
    missing = sorted(set(AGING_BUCKET_LABELS) - declared["recon_breaks_export"])
    assert not missing, f"the export schema is short these aging buckets: {missing}"


def test_the_dataset_is_configuration_rather_than_a_literal() -> None:
    """It was hardcoded under a comment claiming it was configurable."""
    source = (
        REPO_ROOT / "src" / "control_room_handover" / "adapters" / "gcp" / "ops_feeds.py"
    ).read_text(encoding="utf-8")
    assert "settings.bigquery_dataset" in source
    assert '"ops_worklist.' not in source, "the dataset is hardcoded into the adapter again"


# --------------------------------------------------------------------------- #
# The window, which used to come from a clock
# --------------------------------------------------------------------------- #
def test_the_managed_query_windows_on_the_requested_date_not_the_current_one() -> None:
    """Watched failing against the shipped ``DATE_SUB(CURRENT_DATE(), ...)``."""
    assert "CURRENT_DATE" not in managed._SNAPSHOTS_SQL, (
        "the managed window is measured from a wall clock, so a handover for any date but today "
        "reads the wrong window and a book pinned to a past date reads nothing at all"
    )
    assert "@as_of" in managed._SNAPSHOTS_SQL


def test_the_store_windows_on_the_requested_date(feed: LocalOpsFeedAdapter) -> None:
    """Three days back from the book's own as-of is three snapshots, not the whole file."""
    series = feed.snapshots(FeedId.RECON_BREAKS, 3, as_of=demo_book.book_as_of())
    assert [snapshot.as_of for snapshot in series] == [
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
    ]


def test_the_window_ends_at_the_requested_date_rather_than_running_past_it(
    feed: LocalOpsFeedAdapter,
) -> None:
    """A handover for an earlier shift must not read days that had not happened yet."""
    series = feed.snapshots(FeedId.RECON_BREAKS, 14, as_of="2026-08-03")
    assert [snapshot.as_of for snapshot in series] == [
        "2026-07-31",
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
    ]


def test_a_date_the_book_does_not_reach_is_an_empty_series(feed: LocalOpsFeedAdapter) -> None:
    """Which is exactly what a deployment would have got from the clock-based window."""
    assert feed.snapshots(FeedId.RECON_BREAKS, 7, as_of="2027-01-01") == ()


def test_the_store_hands_the_parser_the_same_nested_shape_the_warehouse_does(
    feed: LocalOpsFeedAdapter,
) -> None:
    """DuckDB returns a STRUCT as a dict, exactly as BigQuery returns a RECORD."""
    series = feed.snapshots(FeedId.DISPUTES, 14, as_of=demo_book.book_as_of())
    assert series, "the disputes feed is empty"
    newest = series[-1]
    assert {bucket.label for bucket in newest.aging} == set(AGING_BUCKET_LABELS)
    assert newest.sla_within + newest.sla_due_soon + newest.sla_breached == newest.queue_depth
    assert newest.citation.source_id == "disputes"


# --------------------------------------------------------------------------- #
# The key the dataset stamps onto every table it creates
# --------------------------------------------------------------------------- #
# Watched failing first, on a copy of bigquery.tf with one table's block deleted: the per-table
# assertion names the table, and the count assertion catches a table added later with no block
# at all.
_TABLE_BLOCK = re.compile(r'resource\s+"google_bigquery_table"\s+"(\w+)"\s*\{(.*?)\n\}', re.DOTALL)
_TABLE_KEY = re.compile(r"\n\s*encryption_configuration\s*\{[^}]*?kms_key_name\s*=\s*([^\s#]+)")
_ANY_TABLE_BLOCK = re.compile(r"\n\s*encryption_configuration\s*\{")


def _dataset_default_key() -> str:
    """The key the dataset's ``default_encryption_configuration`` names."""
    block = re.search(
        r"default_encryption_configuration\s*\{(.*?)\n  \}",
        _TF.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    assert block is not None, "the dataset declares no default_encryption_configuration"
    key = re.search(r"kms_key_name\s*=\s*([^\s#]+)", block.group(1))
    assert key is not None, "the dataset's default_encryption_configuration names no key"
    return key.group(1)


def test_every_table_declares_the_key_the_dataset_would_stamp_on_it() -> None:
    """An inherited CMEK key is a REPLACEMENT waiting to happen, and a replaced table is empty.

    The dataset's ``default_encryption_configuration`` makes BigQuery stamp that key onto every
    table it creates in the dataset, so the live table carries an ``encryption_configuration``
    whether or not the Terraform declares one. Terraform then reads the undeclared block as a
    REMOVAL, and removing an encryption configuration FORCES REPLACEMENT: the table is destroyed
    and recreated, and a recreated table holds no rows. Proved by execution against a sibling
    deployment on 2026-09-12, where every loaded table planned as ``must be replaced`` with
    ``encryption_configuration { # forces replacement }`` as the cause.

    CMEK cascades in BigQuery's model and not in Terraform's, which is why the key is named
    twice, and why nothing but a check like this notices when it is named once.
    """
    text = _TF.read_text(encoding="utf-8")
    expected = _dataset_default_key()
    blocks = _TABLE_BLOCK.findall(text)
    assert blocks, "no google_bigquery_table blocks found; the regex or the file moved"

    for name, block in blocks:
        declared = _TABLE_KEY.search(block)
        assert declared is not None, (
            f"google_bigquery_table.{name} declares no encryption_configuration. The dataset "
            "stamps its key onto the table anyway, so the next plan reads the server-set block "
            "as a removal and REPLACES the table, which destroys every row it holds."
        )
        assert declared.group(1) == expected, (
            f"google_bigquery_table.{name} names {declared.group(1)} where the dataset stamps "
            f"{expected}. A table keyed differently from the dataset default is still a "
            "replacement at the next plan."
        )

    # The count is the half that catches a table added LATER with no block at all: iterating the
    # tables found cannot fail over a table nobody declared a key for if nobody looks at how many
    # keys were declared.
    assert len(_ANY_TABLE_BLOCK.findall(text)) == len(blocks), (
        f"{len(blocks)} google_bigquery_table resources and "
        f"{len(_ANY_TABLE_BLOCK.findall(text))} table-level encryption_configuration blocks; "
        "every table needs exactly one, naming the dataset's key."
    )
