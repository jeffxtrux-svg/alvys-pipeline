# Architecture

This page explains *why* the pipeline is shaped the way it is. The
source-by-source detail lives in the connector pages; here we cover the ideas
that are true across all of them.

## Carrier identity (ground truth)

Identifiers used across the brief and the federal data sources. Reference
these instead of re-deriving fleet size or DOT number from whatever tile
happens to be on screen — those numbers are downstream snapshots and can
drift (the FMCSA `AvgPowerUnits` field on the CSA scorecard, for example,
is a snapshot of carrier-reported assets and is **not** the current
active-truck count).

| Identifier | Value | Where it's used |
|------------|-------|-----------------|
| Carrier name | **X-Trux, Inc.** | CSA scorecard page header, brief title |
| DOT number | **841776** | `compute_csa_scorecard`, FMCSA SMS, SambaSafety CSA pull |
| MC number  | **375851** | Motor carrier authority — surfaced on the page-10 carrier tile |
| Sister company | X-Linx, Inc. (brokerage) | Shares office overhead with X-Trux for the rate-per-mile goal (see `rate-per-mile-goal.md`) |
| Active power units | **~15 trucks** (live from Alvys; fluctuates) | Computed every run and rendered on the page-1 "Active Trucks · MTD" tile. **Use that tile as the live source of truth.** Recent baseline is ~15 — anything dramatically larger on a downstream tile (e.g. Samsara fleet totals reporting 50+ trucks of activity) is a sign the source feed is unfiltered. |

The hardcoded fallbacks in `build_csa_scorecard_page` are kept in sync
with this table — if FMCSA reassigns either number, update both this
section and the literal in `src/scorecard_email.py`. Active-truck count is
intentionally **not** pinned — only the recent baseline is recorded so
future agents have a sanity-check anchor without falsely freezing the
number.

**Why FMCSA's "Avg Power Units" doesn't match.** The CSA scorecard page
shows `AvgPowerUnits` from FMCSA's carrier-of-record snapshot — that's
historical and counts whatever X-Trux has on file with FMCSA, including
power units that may no longer be in active service. Don't reach for that
tile as a fleet-size proxy; use the page-1 Active Trucks tile instead.

## The problem being solved

XFreight runs on three SaaS systems that don't talk to each other:

- **Alvys** — the TMS (transportation management system): loads, trips, fuel.
- **Samsara** — telematics: where the trucks are, how they're driven, inspections.
- **QuickBooks** — accounting, kept in *five separate company files*.

The business wants **one set of Power BI dashboards** spanning all three. Power
BI is happiest reading tabular files from a known location. So the job of this
repo is to be the glue: pull from each API, normalize to tables, and stage them
where Power BI can find them.

## Why Excel-in-OneDrive (and not a database)?

A database would be the "proper" answer, but it adds hosting, credentials,
backups, and a gateway for Power BI. Excel-in-OneDrive was chosen because:

- Power BI connects to OneDrive/SharePoint files **with no on-prem gateway**.
- The business already had a hand-maintained `Alvys_Master.xlsx`; matching its
  schema let the existing report keep working with zero rebuild.
- It's debuggable by a non-engineer — you can open the file and look.

The tradeoff (file locks, the awkward "iterate pipeline then refresh" loop) is
real, which is why an **API-direct alternative** exists for Alvys — see
[powerbi.md](./powerbi.md).

## The shared four-step pattern

Every connector is an instance of the same pipeline. Learn it once:

### 1. PULL — an API client class

Each source has a client (`AlvysClient`, `SamsaraClient`, `QBClient`) that owns
two concerns: **authentication** and **pagination**. The three auth styles
differ (see table below) but the shape is identical: a client object holds
credentials, lazily fetches a token, and exposes `fetch_*` methods that return
plain `list[dict]` of raw JSON records.

| Source | Token mechanism | Pagination |
|--------|-----------------|------------|
| Alvys | OAuth2 client-credentials, JSON body w/ `audience` (Auth0-style); token cached until ~60s before expiry | page/pageSize numbers via POST `/…/search` body |
| Samsara | Static long-lived API token in the `Authorization` header | cursor: `pagination.endCursor` → `after` param |
| QuickBooks | OAuth2 refresh-token; **rotates** a new refresh token on every refresh; auto-retries once on 401 | report endpoints aren't paged; entity queries use `MAXRESULTS` |

### 2. TRANSFORM — JSON → rows

This is where the connectors diverge most:

- **Alvys** uses a *declarative* approach. `column_mappings.py` is a big list of
  `(excel_column_name, accessor)` tuples. An accessor is either a dotted path
  string (`"Stops.first.Address.City"`) or a Python callable for computed
  columns. `transformers.py` walks each mapping against each record. This exists
  because the target schema (the legacy `Alvys_Master.xlsx`) has 200+ specific
  columns that must match exactly.
- **Samsara** uses `pandas.json_normalize` to flatten nested JSON generically —
  no hand-mapping, because the Samsara sheets are new (not matching a legacy file).
- **QuickBooks** has a *recursive* parser because QB report JSON is a tree of
  nested `Section`/`Data`/`Summary` rows, not a flat list.

### 3. WRITE — rows → .xlsx

- Alvys: `output_writer.py` is fussy on purpose. The legacy master stored dates
  as `MM-DD-YYYY` text (converted to America/Chicago) and certain ID columns as
  Excel integers; Power Query's "Changed Type" steps were authored against those
  exact formats, so we reproduce them or the report breaks.
- Samsara/QB: simpler `to_excel`, with a sanitizer that strips ASCII control
  characters openpyxl rejects.

### 4. UPLOAD — .xlsx → OneDrive

All three share **one** module, `onedrive_upload.py`, which talks to Microsoft
Graph using a single Azure app registration (client-credentials,
`Files.ReadWrite.All`). The Samsara and QB upload scripts just import its
`get_token` / `ensure_folder` / `upload_file` helpers and point them at a
different folder. Uploads use a resumable upload session (10 MiB chunks) with
`conflictBehavior: replace`. See [onedrive-and-alerts.md](./onedrive-and-alerts.md).

## Design principles you'll see repeated in the code

- **Fail soft on optional data.** Reference-data fetches and whole reports are
  wrapped in try/except so one 404 or one bad company doesn't kill the run.
  Missing data becomes blank columns, not a crash. (`_safe_get`,
  `_try_get_optional`, per-report try/except.)
- **Endpoint discovery by fallback.** APIs move; several fetchers try a list of
  candidate paths/filters and keep the first that works (Alvys
  `_fetch_with_fallback`, Samsara IFTA/HOS/safety path lists).
- **Verbose, structured logging.** Every step logs page counts and running
  totals. The Alvys run also dumps `output/_debug/sample_*.json` and a rate /
  carrier inventory so you can fix a wrong field path without re-instrumenting.
- **Idempotent outputs.** A run fully rewrites its file(s); uploads replace.
  Re-running is always safe.

## How a run actually flows (Alvys example)

```
src.main
  ├─ load_dotenv(), read ALVYS_CLIENT_ID/SECRET, ALVYS_START_DATE
  ├─ lookups.build_lookups(client)          # drivers, trucks, carriers, customers…
  ├─ client.fetch_loads / fetch_trips / fetch_fuel
  ├─ lookups.build_join_index(loads, trips) # LoadNumber ↔ trip/load join
  ├─ client.fetch_invoices → build_invoice_index
  ├─ dump _debug samples + rate/carrier inventory
  ├─ transform_records(raw, LOADS_COLUMNS) … (×3)
  └─ write_master_xlsx(loads, trips, fuel) → output/Alvys_Master.xlsx
```

The other two connectors are simpler variants of this same skeleton.
