# bigquery.tf : the F1 / F2 ops-worklist export dataset this vertical reads (CMEK, read-only).
#
# THIS FILE DID NOT EXIST. `adapters/gcp/ops_feeds.py` has always queried two export tables, and
# nothing in this directory created either of them: no dataset, no table, no API, no IAM role and
# no CMEK binding. The adapter referred to a store with no existence anywhere in the deployment,
# so the managed profile would have failed at its first request with a not-found. All five arrive
# together, because a dataset missing any one of them fails a different silent way.
#
# These tables are the CONTRACT between this service and its two upstream feeds: F1
# (ops-recon-breaks-engine) writes the shape, F2 (disputes-chargebacks-manager) conforms to it,
# and a third feed is a table and an enum member rather than a second parse. Declaring them here
# does not make this service their owner: it holds dataViewer and nothing more (iam.tf), and in
# production the rows are written by the feeds. For a DEMO deployment they come from
# `scripts/load_demo_book.py`, which runs as an operator and never as the service.
#
# General Principle map:
#   P-03 (residency): created in the EFFECTIVE region, so worklist rows about a bank's own
#         operations never leave the deployment's country. `location` is OPTIONAL on this
#         resource, so a null would not fail the plan: it would silently create the dataset in
#         the US multi-region and break residency with a green gate. var.region defaults to null;
#         local.region is the resolved one.
#   P-09 (CMEK explicit): the dataset encrypts under the regional key from kms.tf. CMEK does not
#         cascade, so the BigQuery service-agent key binding is declared there alongside it.
#   P-04 (data minimisation): the columns below are exactly the ones the adapter reads
#         (`SELECTED_COLUMNS`), and a contract test holds the two together.

resource "google_bigquery_dataset" "ops_worklist" {
  dataset_id  = "ops_worklist" # matches CONTROLROOM_BQ_DATASET
  project     = var.project_id
  location    = local.region # P-03
  description = "F1 and F2 ops-worklist snapshot exports for control-room-handover (internal, CMEK)."

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.cmek.id # CMEK does not cascade (P-09)
  }

  delete_contents_on_destroy = false

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.bigquery,
  ]
}

# The published export contract, identical for both feeds. `as_of` is a DATE because the window
# is a date range: the adapter used to measure it from CURRENT_DATE() while the handover request
# carried its own as-of, so a pack written for any date but today read the wrong window and
# reported the requested one in its heading. The predicate now takes that date as a parameter.
#
# `aging`, `sla` and `source` are RECORDs rather than flattened columns because that is the shape
# the feeds publish and the shape the shared row parser reads. The offline store holds the same
# three as DuckDB STRUCTs, so both sides hand the parser the same nested dicts.
locals {
  ops_export_schema = jsonencode([
    { name = "feed_id", type = "STRING", mode = "REQUIRED" },
    { name = "as_of", type = "DATE", mode = "REQUIRED" },
    { name = "queue_depth", type = "INTEGER", mode = "REQUIRED" },
    {
      name = "aging", type = "RECORD", mode = "REQUIRED",
      fields = [
        { name = "0-1d", type = "INTEGER", mode = "REQUIRED" },
        { name = "1-3d", type = "INTEGER", mode = "REQUIRED" },
        { name = "3-7d", type = "INTEGER", mode = "REQUIRED" },
        { name = "7d+", type = "INTEGER", mode = "REQUIRED" },
      ]
    },
    {
      name = "sla", type = "RECORD", mode = "REQUIRED",
      fields = [
        { name = "within", type = "INTEGER", mode = "REQUIRED" },
        { name = "due_soon", type = "INTEGER", mode = "REQUIRED" },
        { name = "breached", type = "INTEGER", mode = "REQUIRED" },
      ]
    },
    { name = "throughput", type = "INTEGER", mode = "REQUIRED" },
    {
      name = "source", type = "RECORD", mode = "REQUIRED",
      fields = [
        { name = "feed", type = "STRING", mode = "REQUIRED" },
        { name = "partition", type = "STRING", mode = "REQUIRED" },
      ]
    },
  ])
}

resource "google_bigquery_table" "recon_breaks_export" {
  dataset_id          = google_bigquery_dataset.ops_worklist.dataset_id
  table_id            = "recon_breaks_export"
  project             = var.project_id
  deletion_protection = true
  schema              = local.ops_export_schema
}

resource "google_bigquery_table" "disputes_export" {
  dataset_id          = google_bigquery_dataset.ops_worklist.dataset_id
  table_id            = "disputes_export"
  project             = var.project_id
  deletion_protection = true
  schema              = local.ops_export_schema
}

# The manifest the demo loader writes LAST, because it records the load that wrote the others.
# It is deliberately not one of this repository's own tables: `hex_service_kit.demobook` keeps it
# out of `TABLES` and appends it in `load_order()`, and the loader creates nothing, so a manifest
# missing from here is a load that exits on a not-found before writing a single row.
#
# `as_of_date` is the date a demo asks the deployment for. The book is windowed from its own
# as-of rather than from today's, so it does not empty itself as it ages.
resource "google_bigquery_table" "book_manifest" {
  dataset_id          = google_bigquery_dataset.ops_worklist.dataset_id
  table_id            = "book_manifest"
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "book_version", type = "STRING", mode = "REQUIRED" },
    { name = "as_of_date", type = "DATE", mode = "REQUIRED" },
    { name = "fictional", type = "BOOL", mode = "REQUIRED" },
    { name = "loaded_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "source_commit", type = "STRING", mode = "NULLABLE" },
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
  ])
}
