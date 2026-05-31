# Operations runbook

Practical "how do I…" recipes for running, debugging, and extending the
pipeline. For the *why* behind any of this, follow the links back to the
connector pages.

## Run a connector locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill in credentials (see note below)

python -m src.main                 # Alvys   → output/Alvys_Master.xlsx
python -m src.samsara_main         # Samsara → output/samsara/Samsara_Master.xlsx
python -m src.qb_main              # QuickBooks → output/quickbooks/QB_*.xlsx
```

Each pull is independent; you can run just the one you're working on. The upload
steps are separate modules you run after a pull:

```bash
python -m src.onedrive_upload          # uploads Alvys_Master.xlsx
python -m src.samsara_onedrive_upload  # uploads Samsara file
python -m src.qb_onedrive_upload       # uploads all QB_*.xlsx
python -m src.samsara_alerts           # checks faults/DVIRs, emails if needed
```

> **Credentials:** `.env.example` lists every variable for all three
> connectors, the OneDrive uploads, and the alerts — copy it to `.env` and fill
> in real values. The full reference table is in
> [automation-and-secrets.md](./automation-and-secrets.md).

## Run / inspect in GitHub Actions

- **Trigger manually:** Actions tab → pick the workflow → *Run workflow*.
- **Get the output without OneDrive:** every run uploads `output/` as an
  artifact (7-day retention) — download it from the run's summary page. This
  includes the Alvys `_debug/` samples.
- **Check the schedule:** crons are in the workflow YAML, in **UTC**
  (~6am/12pm/6pm Central; QB offset +30 min).

## Debugging recipes

### An Alvys column is blank when it shouldn't be
1. Open `output/_debug/sample_loads.json` (or `_trips` / `_fuel`).
2. Find the real field name/path for that value.
3. Fix that one `(column, accessor)` entry in `src/column_mappings.py`.
4. Re-run `python -m src.main`. The log's `report_blank_columns` warning lists
   what's still empty.

### Alvys log shows `SCHEMA DRIFT — N column path(s)…`
A field name in Alvys' JSON changed and `column_mappings.py` still references the
old key, so the column would silently go blank. The warning names each broken
path with **the sibling keys that *are* present** on the parent dict — the new
field name is almost always in that list. Fix:
1. Note the broken column and the `broken_at` path from the warning.
2. Check `output/_debug/sample_<loads|trips|fuel>.json` to confirm the new key
   name (cross-reference with the `Sibling keys present:` line).
3. Update that one tuple's accessor in `src/column_mappings.py` and re-run.

Drift is reported only when **zero records** resolve the path and at least one
record's parent dict was reachable — empty stops or missing optional sub-objects
are correctly ignored (won't false-positive). Callable accessors are skipped
(can't be statically validated).

### A whole Alvys reference lookup failed
The log prints `<name>: FAILED (…)` and those enriched columns stay blank. The
fetch tried GET then several POST `/search` filter shapes; check the logged HTTP
codes. Optional sources (offices/subsidiaries/carriers/customers/invoices)
degrade gracefully — the rest of the run still succeeds.

### A Samsara data type is empty
Look for `GET … → HTTP 4xx — skipping (check API token scope)`. This is almost
always a **token scope** issue — regenerate the Samsara token with Full Access
(or at least Fleet Read + Safety Read).

### Samsara: blanket 401s
Check the `Authorization` scheme in `samsara_client._headers`. Current correct
value is `Bearer <token>` (the docstring's "Token" note is stale — see
[connector-samsara.md](./connector-samsara.md)).

### QuickBooks: a company is skipped
`Skipping <company> (no credentials)` means it's missing its refresh token or
realm ID. The N&J pair are intentionally skipped until onboarded.

### QuickBooks: refresh-token errors
Intuit rotates the refresh token every run and `qb_main` writes the new one back
to GitHub Secrets via `gh secret set`. If you ran locally, you may have advanced
the token out from under GitHub (or vice-versa). Pull the current value from
Secrets, or test with a throwaway token. If rotation in CI fails, you have ~100
days on the old token to fix `GH_PAT` before it expires.

### OneDrive upload fails
- `401` from the token endpoint → bad `AZURE_CLIENT_SECRET` or wrong tenant/client.
- `403` on upload → app missing `Files.ReadWrite.All` consent, or the
  `ONEDRIVE_USER_UPN` has no OneDrive provisioned.
- Alerts silent but uploads fine → missing `Mail.Send` consent.

### Alvys rate-limited (429)
Increase the inter-page delay (`time.sleep(0.2)`) in
`alvys_client._paginate_search`.

## Scorecard email runbook

The daily scorecard (`scorecard_email.yml`, 7am CST) logs an **OneDrive
preflight** block at the top of every run — this is the primary diagnosis
surface. Open the latest run, scroll to the start, find:

```
OneDrive preflight: N of 8 expected files found
  FOUND    Alvys Master 2026   ...   (3 sheet(s), 4120 rows)
  MISSING  QB AR aging         ...   (required)
  absent   SambaSafety Master  ...   (optional)
```

Each line below maps a preflight outcome to its fix. `MISSING` lines also
appear as a warning banner at the top of the email.

### MISSING  Alvys Master 2026
The hand-maintained workbook the Power BI report reads (and the scorecard reads
for closed-month KPIs and page 1). Not produced by any pipeline job.
- **Fix:** confirm `Alvys Master 2026.xlsx` exists in the OneDrive root for
  `ONEDRIVE_USER_UPN`. If you renamed it, update `SCORECARD_ALVYS_PATH` in
  `.github/workflows/scorecard_email.yml`. To bypass the by-name lookup when a
  duplicate exists, set `SCORECARD_ALVYS_SHARE_URL` to a Graph share link.

### MISSING  Alvys Pipeline
The fresh pipeline pull (`Alvys Pipeline.xlsx`, written by `refresh.yml`).
Drives pages 4–8 (driver mileage, uninvoiced loads, Alvys AR, recon).
- **Fix:** open the latest `Refresh Alvys data` run. If it failed, debug the
  Alvys pull (see `An Alvys column is blank…` above). If it succeeded but the
  scorecard still can't find the file, check `ONEDRIVE_TARGET_FILENAME` in
  `refresh.yml` matches `SCORECARD_ALVYS_PIPELINE_PATH` in `scorecard_email.yml`
  (defaults: `Alvys Pipeline.xlsx` in both).

### MISSING  QB P&L / QB AR aging / QB AR history / QB AP history
The QuickBooks refresh didn't produce one or more of `QB_ProfitAndLoss.xlsx`,
`QB_AgedReceivableDetail.xlsx`, `QB_AR_History.xlsx`, `QB_AP_History.xlsx`
under `QuickBooks/` in OneDrive.
- **Fix:** open the latest `Refresh QuickBooks data` run. The two most common
  causes: a refresh-token rotation failure (see `QuickBooks: refresh-token
  errors` above) or an expired `GH_PAT` that broke rotation 100+ days ago. If
  only one company is missing, the loop logged a per-company skip — check its
  refresh token.

### MISSING  Samsara Master
The Samsara refresh didn't upload `Samsara/Samsara Master.xlsx`.
- **Fix:** open the latest `Refresh Samsara data` run. Most common cause is a
  stale `SAMSARA_API_TOKEN` (blanket 401s — see the Samsara recipe above).

### absent  SambaSafety Master  (optional)
**Expected** until the SambaSafety export feed is wired up — page 9 renders a
placeholder and the run is not flagged as failed.
- **To wire it up:** configure a scheduled export in the SambaSafety admin
  portal that lands a workbook at `SambaSafety/SambaSafety_Master.xlsx` in
  OneDrive, with a `Drivers` sheet (driver, license #, state, status,
  expiration, risk score, risk category) and a `Violations` sheet (driver,
  date, type, points, state, severity). `compute_sambasafety` fuzzy-matches
  column names, so minor header variations are fine. Override the path with
  `SCORECARD_SAMBASAFETY_PATH` if you put it elsewhere.

### Scorecard ran but no email arrived
The job succeeded but no message landed. Search the run log for
`Scorecard email sent to:` — if absent, the Graph `sendMail` call failed and
the error is logged just before that point.
- **Fix:** most common is missing `Mail.Send` consent on the Azure app (same
  permission the Samsara alert job uses — if those have ever sent, this isn't
  it). Second most common: `SCORECARD_TO_EMAILS` is empty or malformed; the
  job parses it as comma-separated.

### Email arrived but a whole page is blank
Cross-reference with the preflight block. All-`FOUND` plus a blank page means
the issue is inside the `compute_*` function for that page, not the file read.
- **Quick mapping:** page 1 reads `Alvys Master 2026` + QB P&L + QB AR + Samsara.
  Pages 4–8 read `Alvys Pipeline`. Page 2 reads Samsara. Page 3 reads QB AR.
  Page 9 reads SambaSafety. The blank page tells you which feed to investigate
  even when preflight passed (e.g. an empty sheet, or a renamed column the
  fuzzy matcher missed).

## Onboarding a new QuickBooks company (N&J Trailers / Properties)

1. Complete the Intuit OAuth connect flow for that company to obtain its
   **realm ID** and an initial **refresh token**.
2. Add GitHub secrets: `QB_NJ_TRAILERS_REFRESH_TOKEN` (and/or `…PROPERTIES…`).
3. Set the realm ID — either add it to the workflow env
   (`QB_NJ_TRAILERS_REALM_ID`) or hardcode it in `qb_main._companies()` like the
   other three (realm IDs aren't secret).
4. Re-run `qb_refresh.yml`. The loop now includes the company automatically; its
   rows appear in every `QB_*.xlsx` tagged with the new `Company` value.

## Adding a brand-new data source

The pattern is fixed (see [architecture.md](./architecture.md)): write a
`<source>_client.py` (auth + paginate + `fetch_*`), a `<source>_main.py`
(orchestrate + flatten + write Excel), and a `<source>_onedrive_upload.py` that
reuses the shared Graph helpers from `onedrive_upload.py`. Add a workflow modeled
on the existing three. Reuse `_safe_get`-style soft-failure and verbose logging.

## Safe-to-assume invariants

- Re-running any job is idempotent: it fully rewrites its output and uploads
  with `replace`.
- One source failing never affects the others — they're separate jobs.
- Missing optional data becomes blank cells, not a crash.
- No data is ever written back to the source systems — this pipeline is
  **read-only** against Alvys/Samsara/QB (the only write-back is the QB refresh
  token into GitHub Secrets).
