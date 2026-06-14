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
  `_trips`/`_fuel`/`_invoice`), find the real path, fix that one tuple, re-run.
  No other code changes needed. The log's `report_blank_columns` lists what's
  still empty. Helpers like `_customer_invoice_field([...])` and `_customer_name`
  fall back through several candidate field names — add to the candidate list if
  the real field has a different name. For load↔QB joins the matching key is
  the **Alvys Load #** vs QuickBooks' **"T" + load #** invoice `Num` (handled by
  `_norm_inv` stripping a leading alpha prefix).
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

Every workflow uses the same **DST-proof pattern**: cron times are armed for both CDT (UTC-5) and CST (UTC-6), and a `Gate to allowed CT hours` step at the top of the job exits cleanly when the current `TZ=America/Chicago` hour isn't in the target set. So Central wall-clock time stays constant year-round with no manual cron edits at the DST flip.

| Workflow | Target (Central) | UTC crons | Hours gated to |
|----------|------------------|-----------|----------------|
| `refresh.yml` (Alvys) | 4am / 11am / 5pm | `0 9,10,16,17,22,23 * * *` | `{4, 11, 17}` |
| `samsara_refresh.yml` | 4am / 11am / 5pm | `0 9,10,16,17,22,23 * * *` | `{4, 11, 17}` |
| `qb_refresh.yml` | 4am / 11am / 5pm | `0 9,10,16,17,22,23 * * *` | `{4, 11, 17}` |
| `sambasafety_refresh.yml` (CSV-drop) | 1am + 3am (pre-brief) + every 2h 4am–6pm | `0 0,6-23 * * *` (hourly arms) | `{1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 18}` |
| `sheets_refresh.yml` | 4:30am / 1:00pm / 5:30pm | `30 9,10`, `0 18,19`, `30 22,23 * * *` | `{4, 13, 17}` |
| `scorecard_email.yml` (13-page brief) | 5:00am (primary) + defense-in-depth backups at 5:15 / 5:30 / 6:30 / 7am | `0,15,30 10` + `0,30 11` + `0 12 * * *` | `≥ 5`, skip `6` |
| `scorecard_healthcheck.yml` (recover dropped runs) | 6:00am — checks OneDrive marker; dispatches scorecard if missing | `0 11,12 * * *` | `{6}` |
| `daily_upload.yml` (MTD load report) | 5:00am | `0 10,11 * * *` | `{5}` |
| `daily_upload_healthcheck.yml` (recover dropped runs) | 6:00am — checks `DailyUpload/sent-*.txt` marker; dispatches daily upload if missing | `0 11,12 * * *` | `{6}` |
| `karpathy_compile.yml` (Karpathy-Wiki librarian) | 7:15am / 1:00pm (each with 30-min backup) | `15,45 12,13`, `0,30 18,19 * * *` | `{7, 13}` |

**Off-GitHub backstop (`ops/cron-trigger/`).** All of the above — staggered
backup crons *and* the 6am healthchecks — are built on GitHub's own `schedule:`
cron, which is best-effort and silently drops runs under load. On 2026-06-08 it
dropped the entire morning batch (every scorecard/daily-upload slot **and** both
healthchecks), so nothing emailed. A small Cloudflare Worker
(`ops/cron-trigger/worker.js`, runs on Cloudflare's scheduler) is the one layer
outside GitHub: each morning (5:30am CT — dual UTC crons + an in-Worker
America/Chicago hour-gate for DST) it dispatches the two **healthcheck**
workflows via the GitHub API. Because the healthchecks
are marker-gated, this is idempotent — it no-ops on normal mornings and recovers
the send on drop mornings. Setup (a fine-grained PAT scoped to Actions:RW on
this repo, stored as a Cloudflare secret) is in `ops/cron-trigger/README.md`.

The daily brief (`src/scorecard_email.py`) is 13 pages scoped to **X-Trux + X-Linx** (JW Logistics excluded throughout via a hardened name matcher in `_is_ar_excluded`). Page 1 is the executive overview; the detail pages 2–13 are grouped into four sections (a `SAFETY` / `OPERATIONAL` / `CSA SCORECARD` / `ACCOUNTING` banner is rendered above each page title by `_header(..., section=...)`):

1. **Overview** — bottom-line + entity P&L + AR/AP trend + AR tiles + **QB-vs-Alvys AR reconciliation** + Alvys 61+ spot-check + safety tiles + 6-month safety trend + **X-Trux rate-per-mile goal** (the "cost-out": live driver-pay/mi from Alvys + shared X-Trux+X-Linx office overhead/mi from QB ÷ a target operating ratio — see `compute_rpm_goal` and `docs/knowledge-base/rate-per-mile-goal.md`). `build_page1` renders in two halves (`part='overview'` then `part='rest'`) so the **bill-by-bill matching page (`build_page8`)** is inserted between the AR reconciliation and the Overdue Invoices table — the variance gets its drill-down on physical PDF p5 rather than at the end of the brief. The `recon_note` carries forward `_pgref` cross-references that auto-resolve to whatever physical pages the targets land on.

   *SAFETY (pages 2–6):*
2. Driver compliance — SambaSafety MVR + license status, plus DOT medical-card expirations from the Alvys Drivers sheet (`build_page9`; SambaSafety section is optional, medical-card section needs only the Alvys feed). See `docs/knowledge-base/connector-sambasafety.md` and `docs/knowledge-base/connector-alvys.md`.
3. Safety & compliance detail (last 24h events / HOS violations / DVIR defects / coaching) (`build_page2`). Fleet avg safety score comes from Samsara's per-driver safety-score endpoint — `samsara_client.fetch_driver_safety_scores` discovers a working path by fallback (the `/fleet/drivers/{id}/safety/score` path 404s; the `/v1/...` legacy path still works). The Coaching-needs-assigned list shows a **Coach** column (manager who closed the session, from `coachedBy.name` on the safety event) and an **Ack** column (✓ when every event for that driver in the 30-day window has been coached/dismissed/recognized in Samsara). Ack state is derived from each event's status on the SafetyEvents sheet — **not** the CoachingSessions sheet; Samsara's `/coaching/sessions` endpoint 404s for our account so that sheet is an empty placeholder. Drivers stay on the list until acked, then for 3 more days as a closeout indicator.
4. Per-driver Samsara safety scores (`build_page2b`) — split off page 3 so the Speed-Over-Limit table and the per-driver score table each get a full page.
5. Equipment compliance — tractor inspections (`build_page_equipment(kind='tractors')`, fed by `compute_equipment` over the Alvys Trucks sheet with `Maintenance` DOT-inspection dates overlaid).
6. Equipment compliance — trailer inspections (`build_page_equipment(kind='trailers')`).

   *OPERATIONAL (pages 7–9):*
7. Driver mileage by settlement week (`build_page4`).
8. Fleet operations — MPG best/worst + speeders (`build_page_fleet`).
9. Fleet idle — all trucks ranked by avg idle/wk over 5 settlement weeks, with per-week idle hours, idle %, idle-gallons est. (`idle_hours × 0.8 gph` fallback) and MPG (`build_page_idle`).

   *CSA SCORECARD (page 10):*
10. **FMCSA carrier scorecard** — BASIC percentile ranks for X-Trux, Inc. (DOT #841776) from the SambaSafety CSA2010 Preview Scorecard CSV (`build_csa_scorecard_page`; data shape from `compute_csa_scorecard`). Each BASIC is flagged INTERVENTION LIKELY when its percentile crosses the FMCSA threshold — `65th` for Unsafe Driving and Crash Indicator, `80th` for all others (`_CSA_INTERVENTION`). Fails soft: if `CSA2010 Preview Scorecard.csv` is absent from `OneDrive/SambaSafety/`, the page is **skipped entirely** (no placeholder ships); it re-appears automatically when the CSV is present. See `docs/knowledge-base/connector-sambasafety.md § The CSA Scorecard report`.

   *ACCOUNTING (pages 11–13):*
11. AR overdue (31+ days) from QuickBooks + Alvys un-invoiced loads + 90+ AR, combined (`build_page_ar_accounting`). Top section is the QB AR overdue list; the lower sections are the un-billed gap behind most of the QB-vs-Alvys variance plus the 90+ collections list.
12. QB-vs-Alvys reconciliation by customer (`compute_ar_customer_reconciliation`; rows sum to the page-1 variance) (`build_page7`).
13. Bill-by-bill matching (`compute_bill_reconciliation`) — auto-picks the best key between Alvys invoice # / Load # vs QB `Num`, with `_norm_inv` stripping a leading alpha prefix (handles QuickBooks' "T" + load-number convention) (`build_page8`).

All times are **Central wall-clock year-round** via the dual-cron + CT-hour-gate pattern above. `sambasafety_refresh.yml` is armed **hourly** (not just at the target±1 UTC hours) because GitHub delivered its old 2-fires/day crons 2–5 hours late every night of 2026-06-05→12 and the single-hour gate skipped every run while showing green — with hourly arms plus a multi-hour target set, a drift-delayed fire just catches the next slot. SambaSafety is also **CSV-drop only** as of 2026-06-12: the API token expired 2026-06-02 (`Forbidden` on every call) and the owner chose to retire API mode — `SAMBASAFETY_API_TOKEN` is intentionally not passed in the workflow, which makes `src/sambasafety_main.py` read the CSVs that Power Automate drops into `OneDrive/SambaSafety/` several times a day. Pulls (Alvys / Samsara / QB) fire concurrently at **4am / 11am / 5pm CT**; the scorecard email primary follows at **5:00am CT** with backup slots through ~6am CT; the Google Sheets KPI dashboard refresh runs at **4:30am / 1:00pm / 5:30pm CT** (three updates per day so the dashboard tracks the same morning / midday / evening cadence as the OneDrive pulls). Manual `workflow_dispatch` / `workflow_call` / `push` triggers all bypass the season gate so on-demand runs work at any hour. The DST flip in early-Nov / mid-Mar requires no code changes.
QuickBooks rotation needs `GH_PAT` (→ `GH_TOKEN`) so the job can `gh secret set`
the new refresh token; without it the run still works but warns and the old
token lasts ~100 days.

## Configuration

`.env.example` documents every variable for all connectors, both uploads, and
the alerts/scorecard — copy to `.env` for local runs; the same values live in
GitHub Secrets for CI. Notable defaults: Alvys `ALVYS_START_DATE` defaults to
today − 425d (CI pins `2024-01-01`); Alvys CI uploads its computed output to
OneDrive as `"Alvys Pipeline.xlsx"`. **This must stay distinct from
`"Alvys Master 2026.xlsx"`, the hand-maintained workbook the Power BI report
reads — a shared name would make the pipeline overwrite the manual file.** The
daily scorecard email reads that same manual `"Alvys Master 2026.xlsx"` (not the
pipeline output) so its KPIs match the report. The full secret-by-secret
reference is in `docs/knowledge-base/automation-and-secrets.md`.

## Core operating memory — employee responsibilities (org accountability map)

Role-focused brief delivery. Owners get the brief for their area; Jeff + JB
are cc'd on everything not directly owned by them for governance visibility.
Canon: `Karpathy-Wiki/raw/xfreight-employee-responsibilities.md`.

| Person(s) | Owns | Primary brief |
|---|---|---|
| **Audra** | Safety + Compliance · invoice closeout (loads invoiced timely + carrier invoices entered into Alvys) | Safety & Compliance (daily) |
| **Jackson + Dan** | On-time delivery · truck coverage / return loads · drivers hitting 2,750 mi/wk avg · driver dispatching · maintenance on trailers + Truk-Way tractors · overall brokerage (X-Linx) operations | Operational / Maintenance (daily) |
| **Jeff + JB** | Accounting / financial · sales · recruiting | Accounting / Financial (daily); Sales + Recruiting (weekly, Jeff primary, JB cc) |
| **Dan + JB + Jeff** | Consolidated leadership view | Executive (daily) |

When writing brief recipient lists, playbook `owner:` fields, or risk-register
`owner:` fields, route owner-specific items to the person above; cc Jeff + JB
unless they're the primary. New brief workflows use the same hardcoded literal
fallback pattern as `scorecard_email.yml` so the right audience is reached
even if a secret gets emptied.

**Tractor inspections — split ownership by fleet.** *X-Trux* (owner-operator)
tractors fall under Audra's safety + compliance lane solo. *Truk-Way* fleet
tractors are a **shared** responsibility: Audra (safety/CSA Maintenance BASIC)
**plus** Jackson + Dan (Truk-Way tractor maintenance, per the responsibility
row above). Until `main.py` adds `Truck.Fleet.Name` to the Trucks sheet, action
items on Audra's brief can't be split per-fleet — the action's `owner` label
calls out the shared piece explicitly ("Audra (Truk-Way tractors: shared w/
Jackson + Dan)"). Trailer inspections are Jackson + Dan only (Audra's brief
filters trailers out of the equipment action item + the Risk Watch strip's
paired trailer text via `safety_relevant_signals`).

## Core operating memory — read before touching equipment / safety code

- **DOT inspection windows: 120-day company policy ≠ 365-day federal.** The
  brief's Equipment Compliance pages render TWO distinct pills per fleet type:
  - *"Annual inspection (365d federal):"* — the FMCSA rule. A unit listed here
    as OVERDUE is **out of service per federal**. Almost never trips because of
    the company policy below.
  - *"DOT inspection (120d policy):"* — XFreight's voluntary, more-conservative
    120-day window. A unit listed here as OVERDUE is past **company** policy and
    needs scheduling; it is **still federally legal to run**. To actually be
    past the federal 365d a unit would have to be **245+ days past the company
    120d policy** (365 − 120 = 245).
  - When writing prose / playbooks / risk entries about equipment compliance,
    a unit past only the 120d company policy is **flagged as needing
    inspection** — it remains in service. Do not call it "out of service" at
    all (not "per FMCSA," not "per company policy"). The "out of service"
    framing is reserved for the federal 365d threshold; default everywhere
    else to "needs inspection" / "flagged for inspection."
  - Why XFreight runs the tighter 120d: driver safety, equipment condition /
    longevity, protecting CSA Maintenance BASIC score, catching issues at the
    4-month mark vs the 12-month mark.
  - **DOT inspections are covered by X-Trux Inc** for all equipment regardless
    of which entity holds title or whether the unit is pulled by a company
    driver or an OO.
  - Canon: `Karpathy-Wiki/raw/xfreight-dot-inspection-policy.md`.

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
