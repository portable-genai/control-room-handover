# The shipped ops-worklist export book

Everything in these files is **fictional**: an invented control room's own backlog, not a
customer record. There is no per-row tenant tag for that reason.

One file per managed BigQuery table, newline-delimited JSON, each row's keys in that table's
column order. The same files feed four readers, which is the point of them being files:

| Reader | How it reads them |
|---|---|
| the offline profiles | `adapters/local/ops_feeds.py`, through DuckDB, over the same schema and the same date window the warehouse answers |
| the deployment | `scripts/load_demo_book.py`, into `ops_worklist.recon_breaks_export` and `ops_worklist.disputes_export` |
| the contract guard | `tests/unit/test_feed_contract.py`, against `schema/ops_worklist_export.schema.json` |
| the schema guard | `tests/contract/test_demo_book.py`, against `infra/terraform/bigquery.tf` |

They replace `fixtures/ops_worklist/`, which only the offline adapter ever read: the contract was
held against rows the deployment never saw.

## The as-of date, and why nothing is rebased

The book is written against `2026-08-07` and ships eight daily snapshots per feed ending there.
A handover asks for a date, and the window ends at that date: `HandoverRequest` has always
carried `as_of`, the service used to drop it at the port boundary, and the managed adapter filled
the gap with `CURRENT_DATE()`. That is why a demo on a deployment asks for
`demo_book.book_as_of()` rather than today, and why the loader writes these dates unchanged.

Rebasing the rows onto the load date would work too, and it is the wrong trade: the loaded book
would differ from the shipped one, and the two stores would be back to serving different records,
which is the whole thing this book exists to stop.

## The nested blocks

`aging`, `sla` and `source` are RECORDs in BigQuery and STRUCTs in DuckDB. Both return them as
plain dicts, so `adapters/_feed_parser.py` reads one shape from either store and needs no branch.
`aging` must carry every bucket in `AGING_BUCKET_LABELS`: the parser keeps only the labels it
finds, so a missing bucket is silently dropped and the backlog reads short.
