# Ops worklist metrics contract (the F1 to F5 seam)

F5 consumes a versioned JSON contract, the ops-worklist export, that F1
(`recon-breaks-engine`) publishes and F2 (`disputes-chargebacks-manager`) conforms to.
One snapshot row per feed per `as_of` carries: `feed_id`, `as_of`, `queue_depth`, the four aging
buckets, the SLA-clock state counts (`within`, `due_soon`, `breached`), `throughput`, and the
`source` (feed and partition it was read from). The schema is in
[`schema/ops_worklist_export.schema.json`](../schema/ops_worklist_export.schema.json).

## Recorded assumption (bounded coverage)

F1 and F2 do not exist on disk in this wave, and F3 and F4 are deferred, so F5 is bound to the two
feeds that the plan documents (`recon_breaks`, `disputes`) and reads them from declared fixtures.
This repo therefore holds a CONSUMED copy of the contract rather than a pin to F1's published
schema file. The drift guard (`tests/unit/test_feed_contract.py`) validates every golden export
fixture against this schema, so a fixture that stopped conforming fails the build. When F1 lands,
replace this consumed copy with a pin to F1's `schema/ops_worklist_export.schema.json` and keep the
drift guard pointed at the pinned file. A later feed (an F3 or F4 join) is one more `FeedId` member
plus its fixture, never new engine code.

## What F5 does with it

The feed port (`ports/ops_feeds.py`) returns these rows RAW and cited and computes nothing. The
deterministic `ScorecardEngine` owns every derived number: the SLA breach rate, the drain ratio
(throughput over queue depth), the capacity utilisation against the configured staffing baseline,
the capacity call-out, and the per-feed and overall severity. The anomaly engine runs robust-z over
the snapshot series. The model narrates the scorecard and produces no number of its own.
