# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A multi-source data pipeline for XFreight. It pulls from three SaaS systems that
don't talk to each other — **Alvys** (TMS: loads, trips, fuel), **Samsara**
(telematics), and **QuickBooks** (accounting, five separate company files) —
normalizes each to tables, and stages them where Power BI can read them. There
are two staging targets: Excel files in OneDrive (the original) and a Google
Sheets KPI dashboard (newer). A daily executive-brief email reads the staged
OneDrive files and reports KPIs.

There is no database, no web service, no test suite, and no linter config. The
deliverables are `.xlsx` files, Google Sheet tabs, and emails, produced by
batch scripts run from GitHub Actions on a cron.

## Commands

Everything runs as a Python module from the repo root (note the `src.` prefix —
run from the repo root so the package resolves):

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # then fill in credentials

# Pulls (each independent — run only the one you're working on):
python -m src.main                  # Alvys      → output/Alvys_Master.xlsx
python -m src.samsara_main          # Samsara    → output/samsara/Samsara_Master.xlsx
python -m src.qb_main               # QuickBooks → output/quickbooks/QB_*.xlsx
python -m src.sheets_main           # all 3 → Google Sheets KPI dashboard

# Post-pull steps (run after the matching pull):
python -m src.onedrive_upload          # upload Alvys_Master.xlsx
python -m src.samsara_onedrive_upload  # upload Samsara file
python -m src.qb_onedrive_upload       # upload all QB_*.xlsx
python -m src.samsara_alerts           # email if faults/DVIRs found
python -m src.scorecard_email          # read OneDrive files → email daily brief
```

There are no automated tests. "Testing" a change means running the relevant
module and inspecting the log output and the produced `.xlsx`/sheet. The Alvys
run also writes `output/_debug/sample_*.json` (raw first record per endpoint)
and rate/carrier inventory files for debugging field paths.

## The shared four-step pattern

Every connector is the same skeleton; learn it once and the rest follow.

1. **PULL** — a client class (`AlvysClient`, `SamsaraClient`, `QBClient`) owns
   auth + pagination and exposes `fetch_*` methods returning `list[dict]` of raw
   JSON. The three auth styles differ: Alvys = OAuth2 client-credentials (token
   cached); Samsara = static bearer token; QuickBooks = OAuth2 refresh-token
   that **rotates on every run**.
2. **TRANSFORM** — JSON → rows. This is where connectors diverge most:
   - **Alvys** is *declarative*: `src/column_mappings.py` is a large list of
     `(excel_column_name, accessor)` tuples where an accessor is a dotted path
     string (`"Stops.first.Address.City"`) or a callable. `src/transformers.py`
     walks each mapping per record. This exists to match the legacy
     `Alvys_Master.xlsx` schema (200+ exact columns) so the existing Power BI
     report keeps working.
   - **Samsara** uses `pandas.json_normalize` (sheets are new, no legacy schema).
   - **QuickBooks** uses a *recursive* parser because QB report JSON is a tree
     of nested `Section`/`Data`/`Summary` rows.
3. **WRITE** — rows → `.xlsx`. Alvys's `src/output_writer.py` is deliberately
   fussy: it reproduces the legacy file's exact date format (`MM-DD-YYYY` text,
   America/Chicago) and integer ID columns, because Power Query "Changed Type"
   steps were authored against those exact formats.
4. **UPLOAD** — `.xlsx` → OneDrive. All connectors share **one** module,
   `src/onedrive_upload.py` (Microsoft Graph, one Azure app, client-credentials,
   resumable upload with `conflictBehavior: replace`). The other upload scripts
   import its `get_token` / `ensure_folder` / `upload_file` helpers.

## Design principles baked into the code

- **Fail soft on optional data.** Reference-data fetches and whole reports are
  wrapped in try/except so one 404 or one bad company doesn't kill the run —
  missing data becomes blank columns, not a crash (`_safe_get`, per-report
  try/except).
- **Endpoint discovery by fallback.** Several fetchers try a list of candidate
  paths/filters and keep the first that works (Alvys `_fetch_with_fallback`,
  Samsara path lists).
- **Idempotent & read-only.** A run fully rewrites its output and uploads with
  `replace`; re-running is always safe. Nothing is ever written back to
  Alvys/Samsara/QB — the *only* write-back anywhere is the rotated QuickBooks
  refresh token saved into GitHub Secrets.
- **Verbose, structured logging** at every step (page counts, running totals).

## When you most commonly edit something

- **An Alvys column comes back blank:** the value's field path in
  `src/column_mappings.py` is wrong. Open `output/_debug/sample_loads.json` (or
  `_trips`/`_fuel`), find the real path, fix that one tuple, re-run. No other
  code changes needed. The log's `report_blank_columns` lists what's still empty.
- **Adding a QuickBooks company:** the three live companies' realm IDs are
  hardcoded in `src/qb_main.py` `_companies()`; the N&J pair read realm IDs from
  env and are skipped until their refresh tokens exist.
- **Adding a brand-new source:** follow the fixed pattern — `<source>_client.py`
  (auth + paginate + `fetch_*`), `<source>_main.py` (orchestrate + flatten +
  write), `<source>_onedrive_upload.py` reusing the shared Graph helpers, plus a
  workflow modeled on the existing ones.

## Automation (GitHub Actions)

Workflows in `.github/workflows/`, all `workflow_dispatch` + cron, Python 3.11,
upload `output/` as a 7-day artifact (`if: always()`):

| Workflow | Does | Cron (UTC) |
|----------|------|------------|
| `refresh.yml` | Alvys pull → OneDrive → artifact | `0 12,18,0 * * *` |
| `samsara_refresh.yml` | Samsara pull → OneDrive → alerts → artifact | `0 12,18,0 * * *` |
| `qb_refresh.yml` | QB pull (+token rotation) → OneDrive → artifact | `30 12,18,0 * * *` |
| `sheets_refresh.yml` | all 3 → Google Sheets dashboard | `0 13 * * *` |
| `scorecard_email.yml` | read OneDrive → email daily brief | `0 13 * * *` |

Crons are fixed UTC (~6am/12pm/6pm Central; QB offset +30 min to avoid overlap).
QuickBooks rotation needs `GH_PAT` (→ `GH_TOKEN`) so the job can `gh secret set`
the new refresh token; without it the run still works but warns and the old
token lasts ~100 days.

## Configuration

`.env.example` documents every variable for all connectors, both uploads, and
the alerts/scorecard — copy to `.env` for local runs; the same values live in
GitHub Secrets for CI. Notable defaults: Alvys `ALVYS_START_DATE` defaults to
today − 425d (CI pins `2024-01-01`); Alvys CI uploads as `"Alvys Master.xlsx"`
(with a space) to match the Power BI report. The full secret-by-secret reference
is in `docs/knowledge-base/automation-and-secrets.md`.

## Documentation map

The authoritative knowledge base is `docs/knowledge-base/` — start at its
`README.md`. Key pages: `architecture.md` (the *why*), `operations.md`
(debugging recipes + runbook), `automation-and-secrets.md`, and one
`connector-*.md` per source. `powerbi/` holds a proof-of-concept where Power BI
reads the Alvys API directly (Power Query `.pq` + `.dax`), bypassing Excel.
Consult these before large changes; keep them in sync when behavior changes.

## Note on `Karpathy-Wiki/`

`Karpathy-Wiki/` is an unrelated personal knowledge-base project that happens to
live in this repo and has **its own** `CLAUDE.md`. It is not part of the data
pipeline — don't conflate the two.
