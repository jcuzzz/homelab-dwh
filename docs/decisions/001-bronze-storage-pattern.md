# 001 — Bronze storage pattern

| | |
|---|---|
| Status | **DECIDED 2026-10-23: option A1** |
| Affects | `ingest/`, `sql/bronze_schema.sql`, every future silver model |

## Decision

Bronze uses **A1**: one append-only table per export in schema `bronze`. The full export is
appended whenever it differs from the table's most recent load, and every row is tagged with
`_load_id` and `_source_line`. The loader holds no business knowledge: no keys, no diffing,
no types.

Current state and change history are **silver's** job, built later in dbt:

- **Current state:** one staging model per table selects the latest export, ordered by
  `load_log.source_modified_at` and then `load_id`. Not by `load_id` alone, because a
  backfilled older file gets a higher id than the newer file it predates.
- **Change history:** dbt snapshots over the staging models, recording rows that disappear
  from a full export as deletions.
- **Size:** a retention rule (keep the last N loads) is added per table only if growth
  becomes a measured problem.

## Why

- **Raw data first, so existing pipelines can move over before anything is redesigned.**
  Bronze holds each export exactly as it arrived: every value as text, no business rules.
  Older pipelines can be repointed at it as they are, and the fully integrated pipelines
  come later in silver. Migrated pipelines read current data through the silver staging
  models, not bronze tables directly, so none of them has to remember the latest-load filter.
- **Complete snapshots without needing keys.** Every changed export is stored whole, so
  "what did the export say on date X" is a filter on one load. A2 would give the same
  history only if every table's primary key were known, and CASES keys are `UNKNOWN`.
- **It is the industry default for this layer.** Databricks' medallion architecture
  describes bronze as append-only raw data with ingestion metadata, dlt's default write
  disposition is append with a load id, and change tracking (SCD2) conventionally lives in
  the transform layer, not the loader.
- **B solves a problem silver already solves.** Its benefit is that nobody can forget the
  latest-load filter. The staging models fix that once, for every consumer, without a
  second table and a second write per load.
- **Storage is not a concern at this scale.** Unchanged files are skipped, so growth only
  follows real changes, and school data volumes are small. The archive keeps every source
  file, so anything trimmed from bronze later can be rebuilt.

## Options considered

| | A1 full append | A2 changes only | B current + history |
|---|---|---|---|
| What is stored | The full export, each time it changes | Only rows changed since the last load, plus deletion markers | A current table replaced each load, plus a history table |
| Storage growth | Full table per changed export | Changed rows only | As A1 or A2, plus one current copy |
| Querying current data | Filter on latest load | Latest version per key, minus deletes | Plain `select` |
| Needs primary keys | No | Yes | No (unless history is A2) |
| Loader complexity | Low | High: keys, diffing, deletes | Medium: two writes kept consistent |
| Tables per export | 1 | 1 | 2 (or 1 table plus a view) |

## Revisit if

- A CASES export turns out to be large and to change daily, so A1's growth is measurable.
- Migrated pipelines need to read bronze directly rather than through silver. Then add a
  latest-load **view** per table (B's lighter variant): no extra storage, no forgotten filter.
- Silver's latest-load query is slow. Then add an index on
  `bronze.load_log (table_name, source_modified_at desc, load_id desc)`.

## Difference from the reference implementation

The skip check compares a file with its table's most recent load **by `load_id`**: the last
file actually loaded into that table. `load_log_table_latest_idx` is on
`(table_name, load_id desc)` to match that query. The reference also orders by
`source_modified_at`.

Either choice is safe. After a backfill of an older file, this loader loads the next copy of
the current file again rather than skipping it, which stores one extra snapshot and loses
nothing. Ordering by modified time is silver's concern, when it picks current state.

Checked side by side against the reference on the same inputs (walkthrough chapter 10.1):
identical load log, rows and archive. The index is the only difference.

## Bronze contract

Silver depends on exactly this. Any change to the loader must keep all of it.

**Database**

- Schema `bronze`, created by idempotent SQL (`python -m ingest init-db`).
- `bronze.load_log` with columns `load_id` (identity primary key), `source`, `table_name`,
  `source_file`, `source_modified_at` (timestamptz), `archived_file`, `file_sha256`,
  `row_count`, `loaded_at` (timestamptz).
- One table per export: `bronze.<source>__<normalised file stem>`.
- Data columns: normalised header names (lowercase; runs of other characters become `_`;
  a leading digit is prefixed with `_`; at most 63 characters; collisions rejected), all
  `text not null`, values exactly as in the file.
- Tracking columns `_load_id` (bigint, references `load_log`, indexed) and `_source_line`
  (the row's line number in the file).

**Behaviour**

- Append-only. A file identical (SHA-256) to its table's most recent load is skipped.
- A header whose column set differs from the existing table fails; reordering is accepted.
- Each file is all or nothing; a failed file does not stop the others.
- Every file is archived, content-addressed, before loading, and loaded from the archive copy.
- Output never contains row values; database errors are reduced to code and class.

**Interface**

- `python -m ingest init-db` and `python -m ingest load --source <name> [--encoding E] <file|dir>`.
- Configuration from `DATABASE_URL` and `ARCHIVE_DIR`; exit code 1 if any file failed.
