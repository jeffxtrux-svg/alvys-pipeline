# CLAUDE.md

Guidance for AI assistants working in this repo. Read this before editing — most
"why is this weird?" questions are answered below.

## What this repo is

A set of Python ETL pipelines that pull data from three SaaS APIs, write Excel
files, and upload them to a single OneDrive folder that Power BI reads from.

| Pipeline   | Source            | Schedule (UTC cron) | Output                              | OneDrive folder |
|------------|-------------------|---------------------|-------------------------------------|-----------------|
| Alvys      | TMS — loads/trips | 12/18/00 daily      | `Alvys_Master.xlsx` (Fuel/Loads/Trips sheets) | root (`Alvys Master.xlsx`) |
| QuickBooks | Accounting (5 cos)| :30 past the hour   | `QB_*.xlsx` (one per report/entity) | `QuickBooks/`   |
| Samsara    | Fleet telematics  | Same as Alvys       | `Samsara_Master.xlsx` (9+ sheets)   | `Samsara/`      |

Power BI Desktop also has a **direct-to-Alvys** Power Query path under
`powerbi/queries/` that bypasses Excel entirely — same logic re-implemented in
M. Keep the two in sync when changing Alvys column derivation.

## Directory layout

```
alvys-pipeline/
├── src/
│   ├── main.py                  # Alvys entry point: python -m src.main
│   ├── alvys_client.py          # Auth0-style OAuth + paginated /search endpoints
│   ├── column_mappings.py       # ← LOADS_COLUMNS / TRIPS_COLUMNS / FUEL_COLUMNS
│   ├── transformers.py          # records → DataFrame; dot-notation accessor; value unwrapping
│   ├── lookups.py               # ID → name dicts; trip↔load join index; invoice index
│   ├── output_writer.py         # Excel writer; date reformat; int coercion
│   ├── onedrive_upload.py       # Microsoft Graph upload (shared helper module)
│   ├── qb_main.py               # QuickBooks entry point: python -m src.qb_main
│   ├── qb_client.py             # QB OAuth (token rotation lives here)
│   ├── qb_reports.py            # Report/entity definitions + row parser
│   ├── qb_onedrive_upload.py    # Re-uses onedrive_upload helpers
│   ├── samsara_main.py          # Samsara entry point: python -m src.samsara_main
│   ├── samsara_client.py        # Samsara Fleet API (cursor pagination, DVIRs use POST)
│   ├── samsara_alerts.py        # Sends Mail.Send Graph emails on fault codes / DVIR defects
│   └── samsara_onedrive_upload.py
├── powerbi/queries/             # Power Query M (direct-to-API alternative)
├── .github/workflows/
│   ├── refresh.yml              # Alvys
│   ├── qb_refresh.yml           # QuickBooks (writes refresh tokens back to Secrets via gh)
│   └── samsara_refresh.yml      # Samsara + alerts
├── docs/privacy.html            # For Intuit Developer app submission
├── .env.example                 # All env vars in one place
└── requirements.txt             # requests, pandas, openpyxl, python-dotenv
```

`output/` and `.env` are gitignored. Output is also written under
`output/_debug/sample_*.json` — useful when columns come back blank.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # fill in real values
python -m src.main         # Alvys
python -m src.qb_main      # QuickBooks
python -m src.samsara_main # Samsara
```

There is no test suite, no linter config, no formatter. "It runs cleanly and
the resulting Excel opens" is the only acceptance signal.

## Alvys data flow (the most complex pipeline)

```
fetch_drivers / trucks / trailers / users / carriers / customers / offices
                  │
                  ▼
          lookups.build_lookups()           ID → friendly name dicts
                  │
fetch_loads ──┐   │
fetch_trips ──┼──▶│  build_join_index()     LoadNumber → load record / trip record
fetch_fuel ───┤   │
fetch_invoices┘   │  build_invoice_index()  LoadNumber → customer/carrier invoice
                  ▼
        transform_records(records, COLUMN_MAP)
                  │
                  ▼
        DataFrame.map(_unwrap_value)        flatten {Amount, Currency} → scalar
                  │
                  ▼
        write_master_xlsx()                 per-column date reformat + int coerce
                  │
                  ▼
        onedrive_upload                     Graph API resumable upload
```

### Alvys API conventions (memorize these)

The Alvys API returns PascalCase fields and wraps numeric values in small
objects. `transformers._unwrap_value` handles the unwrapping automatically.

- **Money**: `{"Amount": 2000.0, "Currency": 840}` → `2000.0`
- **Distance**: `{"Distance": {"Value": 1270.0, "UnitOfMeasure": "Miles"}, "Source": "..."}` → `1270.0`
- **Quantity**: `{"Value": 174.11, "UnitOfMeasure": "Gallons"}` → `174.11`
- **Stops** is an array — use `Stops.first.*` / `Stops.last.*` in dot-notation paths
- **Driver / Truck / Carrier** appear as `{Id, Fleet}` only — names require a
  separate roster lookup (handled in `lookups.py`)
- **Auth** is Auth0-style: POST JSON body with `audience` parameter (NOT
  form-encoded). See `alvys_client._get_token`.
- **Pagination** is page/pageSize (POST `/search` endpoints). Response shape
  varies — `_paginate_search` tries `Items`/`items`/`data`/`results` keys.

### How `column_mappings.py` works

Each sheet is a list of `(master_column_name, accessor)` tuples. The accessor
is one of:

- `str` — dot-notation path through nested dicts (case-insensitive). Special
  segments `first` / `last` index into lists.
- `callable` — `fn(record) -> value`, used for computed columns, lookups, and
  cross-sheet joins.
- `None` — placeholder for UI-only / real-time fields that don't exist in the
  API. These stay blank intentionally.

Common helper factories (in `column_mappings.py`):

| Helper                          | What it does                                              |
|---------------------------------|-----------------------------------------------------------|
| `_name_from_id(table, path)`    | Look up an ID via a `lookups.*` dict                      |
| `_from_trip(path)`              | On a Load record, hop to joined trip then dot-path        |
| `_from_load(path)`              | On a Trip record, hop to joined load then dot-path        |
| `_name_from_id_via_trip(...)`   | Combo: hop to trip → grab ID → lookup                     |
| `_zero` / `_zero_default(path)` | Cosmetic columns the manual master keeps as 0 / numeric   |
| `driver1_rate(rate_type)`       | Pull rate from legacy `Driver1.Rates` list                |
| `_mileage_pay_from_trip(trip)`  | Driver Rate: V2 tiered → legacy fallback (see below)      |

### "A column is blank that shouldn't be"

This is the most common bug class. Workflow:

1. Run the pipeline. Look at the end of the log — `report_blank_columns` lists
   any column where every value is null/empty.
2. Open `output/_debug/sample_loads.json` (or `_trips`, `_fuel`, `_carriers`,
   etc.). Find the field the column should be reading.
3. Fix the accessor in `column_mappings.py`. The dot-notation resolver in
   `transformers._get_nested` is case-insensitive, so casing doesn't matter.
4. Re-run.

### Driver Rate gotcha (Driver1.Rates vs Driver1.RatesV2)

Alvys is migrating from a flat list (`Driver1.Rates: [{RateType, Rate}, ...]`)
to a structured V2 schema (`Driver1.RatesV2: [{loadedMilesRate: {tiers: [...]}, ...}]`).
Newer trips have V2 only, older trips have legacy only, some have both.

`column_mappings._mileage_pay_from_trip` reads V2 first, falls back to legacy.
**Do not "simplify" this** — May 2026 trips that returned $0 for driver rate
were the diagnostic that uncovered the V2 rollout. Both paths must stay.

Caveat: rates are the driver's *current* rate, not the rate locked at
settlement time. There is no historical field per Alvys support.

### Carrier Rate vs TripValue gotcha

`Carrier Rate` reads `trip.Carrier.Rate.Amount`. `TripValue.Amount` is wrong
for that column — it includes driver pay for company trucks. Only brokered
X-LINX loads have a Carrier object; X-TRUX/XFreight company loads correctly
return blank.

### Date formatting (output_writer.py)

The original manual `Alvys_Master.xlsx` had inconsistent date formats per
column. Power Query's "Changed Type" steps were authored against those
inconsistent formats. We replicate them: all date-like columns are written as
text in `MM-DD-YYYY` (date-only, no time) in America/Chicago. Don't change
this without re-authoring the Power Query steps too.

A column is detected as "date-like" if ≥70% of non-empty values match an ISO
8601 or "human" `MM-DD-YYYY [HH:MM]` pattern (see `_looks_like_date_column`).

### Integer coercion

`INT_COERCE_COLUMNS` in `output_writer.py` lists columns that should be Excel
numeric cells, not text. Each cell is coerced individually — non-numeric
values pass through unchanged. Matches what the manual master had.

## QuickBooks specifics

- Five companies (`_companies()` in `qb_main.py`) — three live, two waiting on
  access from accountant (N&J Trailers, N&J Properties; their realm IDs are
  empty strings, so they get skipped).
- **Refresh tokens rotate on every call**. After each company's pull, the new
  refresh token is written back to GitHub Secrets via `gh secret set`. This
  requires `GH_TOKEN` / `GH_PAT` with `repo` + secrets scope in the workflow.
  If rotation fails, the OLD token stays valid for ~100 days. Don't panic.
- Reports use `date_macro` (e.g. `"This Fiscal Year"`) rather than explicit
  dates so each refresh is automatically current-period.
- Each output Excel stacks all five companies via a leading `Company` column.
- `MINOR_VERSION = 75` — bumping this can change report row shapes; test before
  merging.

## Samsara specifics

- Auth is `Authorization: Bearer <token>` (the docstring says "Token"; the
  code is correct — see commit `f69eabe`).
- **Pagination is cursor-based** (`pagination.endCursor`), not page numbers.
- **Trips require a vehicle ID in the path** — `fetch_trips` loops over every
  vehicle.
- **Vehicle stats: max 4 stat types per request**. We make two calls and
  merge by vehicle ID. See `fetch_vehicle_stats`.
- **DVIRs use POST**, not GET (changed in API v2025.10). All other endpoints
  use GET.
- `samsara_alerts.py` runs as a separate workflow step and emails fault
  codes / unresolved DVIR defects via Microsoft Graph `Mail.Send`. The Azure
  app registration needs `Mail.Send` Application permission granted with
  admin consent.
- `_sanitize_df` strips ASCII control chars before writing to Excel —
  openpyxl refuses to write them.

## OneDrive upload (shared)

`onedrive_upload.py` is the canonical Microsoft Graph helper. `qb_onedrive_upload.py`
and `samsara_onedrive_upload.py` import `ensure_folder`, `get_token`,
`upload_file` from it — don't fork these.

- All three pipelines share **one** Azure app registration (env vars:
  `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`).
- App permissions needed: `Files.ReadWrite.All` (uploads) and `Mail.Send`
  (Samsara alerts), both Application-level with admin consent.
- Always uses an upload session (chunked) regardless of file size — clean and
  consistent.
- Path encoding: `_enc_path` URL-encodes each segment with `safe=""` so
  spaces become `%20`, not `+`. Filenames with spaces work.

## Adding a new column to the Excel output

1. Pick a sheet — `LOADS_COLUMNS`, `TRIPS_COLUMNS`, or `FUEL_COLUMNS` in
   `src/column_mappings.py`.
2. Add a `(name, accessor)` tuple in the position you want.
3. If the field requires data that's not in `raw_loads` / `raw_trips` /
   `raw_fuel` (e.g. a new reference table), extend `lookups.py`:
   - Add the dict at module top
   - Add a fetch + populate block in `build_lookups`
4. Re-run locally — check `report_blank_columns` and `output/_debug/`.
5. If you've added a column that Power BI consumers expect, also mirror it in
   `powerbi/queries/*.pq` and update `powerbi/SETUP.md` if the new column
   needs explanation.

## Adding a new QuickBooks report

Edit `REPORT_CONFIGS` in `src/qb_reports.py`. The report parser handles all
QB report shapes generically — section headers, nested groups, totals — so
just specify the path and params. If the report has a wildly different shape
(e.g. comparative reports), test with one company first.

## GitHub Actions / Secrets reference

Required secrets (per pipeline):

```
# Alvys
ALVYS_CLIENT_ID, ALVYS_CLIENT_SECRET

# QuickBooks
QB_CLIENT_ID, QB_CLIENT_SECRET
QB_XTRUX_REFRESH_TOKEN, QB_TRUKWAY_REFRESH_TOKEN, QB_XLINX_REFRESH_TOKEN
QB_NJ_TRAILERS_REFRESH_TOKEN, QB_NJ_PROPERTIES_REFRESH_TOKEN  # not live yet
GH_PAT  # PAT for rotating refresh tokens back into Secrets

# Samsara
SAMSARA_API_TOKEN
ALERT_TO_EMAILS  # comma-separated

# Shared (OneDrive + Mail.Send)
AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
```

`ONEDRIVE_USER_UPN` and `ALERT_FROM_UPN` are hardcoded to `jeff@xfreight.net`
in the workflow YAMLs — change them there, not in code.

The three workflows run on staggered cron (Alvys/Samsara on the hour,
QuickBooks 30 min later) so they don't fight for OneDrive locks.

## Style conventions

- Python 3.10+ — `from __future__ import annotations` at the top of every
  module, `|` unions, modern typing.
- Logging via `logging.getLogger(__name__)` — no `print`.
- Banner-style separators (`"=" * 60`) bracket each major step in entry
  points. Keep them — they're how log scanning works during long Actions
  runs.
- "Try several known endpoint paths" pattern (`_try_get_optional`,
  `_fetch_with_fallback`) is used liberally because the Alvys / Samsara APIs
  shift endpoint names between versions. Keep the fallback list when adding
  new endpoints.
- Errors during enrichment lookups should never abort the run — wrap them in
  `try/except` and log a warning. Columns that depend on the failed lookup
  stay blank, which is recoverable.
- Don't add comments narrating WHAT the code does. Do add comments when the
  WHY would surprise a reader — see the Carrier Rate, V2 fallback, and date
  formatting blocks for the style.

## Things that look like bugs but aren't

- Some columns in `LOADS_COLUMNS` use `_zero` as their accessor and always
  return 0. They're cosmetic — the manual master had them as 0, so Power
  Query's "Changed Type" step expects a number, not blank.
- `Driver1.Rates` empty for newer trips → not a bug, V2 takes over (see
  Driver Rate gotcha).
- A column visible in `output/_debug/sample_loads.json` that doesn't appear in
  the Excel — check `column_mappings.py`; we only emit columns that were in
  the manual master.
- Fuel sheet writes first (sheet order: Fuel → Loads → Trips). That matches
  the manual master's tab order.

## Branch / commit conventions

- Commits use imperative, sentence-case subjects. Look at recent history with
  `git log --oneline -20`.
- No PR template, no required reviewers — solo project.
- Develop on whatever branch the task spec dictates; don't push to `main`
  without explicit instruction.
