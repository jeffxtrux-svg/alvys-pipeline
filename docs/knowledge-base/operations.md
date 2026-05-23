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

> **`.env` is incomplete.** `.env.example` only covers Alvys + the Samsara token
> + alert recipients. To run uploads or QuickBooks locally you must also add the
> shared Graph vars (`AZURE_*`, `ONEDRIVE_USER_UPN`) and the QB vars. See the
> full table in [automation-and-secrets.md](./automation-and-secrets.md).

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
