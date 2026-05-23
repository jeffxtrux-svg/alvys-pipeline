# Connector: QuickBooks (accounting, 5 companies)

QuickBooks is different from the other two in one big way: there are **five
separate company files** (QBO "realms"), and the job pulls each one and stacks
the results so Power BI can slice across entities. It's also the only connector
that has to **write a secret back to GitHub** on every run.

- **Entry point:** `python -m src.qb_main`
- **Output:** `output/quickbooks/QB_<Report>.xlsx` — one file per report/entity,
  each row tagged with a `Company` column
- **Files:** `qb_main.py`, `qb_client.py`, `qb_reports.py`

## The five companies

Defined in `qb_main._companies()`:

| Company | Realm ID | Refresh-token env var |
|---------|----------|------------------------|
| X-Trux Inc | `9341454573269252` | `QB_XTRUX_REFRESH_TOKEN` |
| Truk-Way Leasing | `9341454569556134` | `QB_TRUKWAY_REFRESH_TOKEN` |
| X-Linx Inc | `9341454574046601` | `QB_XLINX_REFRESH_TOKEN` |
| N&J Trailers | `QB_NJ_TRAILERS_REALM_ID` (env) | `QB_NJ_TRAILERS_REFRESH_TOKEN` |
| N&J Properties | `QB_NJ_PROPERTIES_REALM_ID` (env) | `QB_NJ_PROPERTIES_REFRESH_TOKEN` |

Realm IDs are **not secret** (they're just company IDs), so the first three are
hardcoded. The N&J pair are pending API access — they're read from env and the
loop **skips any company with no token or no realm ID**, so the pipeline runs
fine with three companies today and lights up the other two once you add their
secrets.

## Authentication — `qb_client.py`

OAuth2 **refresh-token** flow against Intuit:

- Token URL: `https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer`
- The token request uses **HTTP Basic auth** — `base64(client_id:client_secret)`
  in the `Authorization` header — with a form body
  `grant_type=refresh_token&refresh_token=…`.
- API base: `https://quickbooks.api.intuit.com/v3/company/{realm_id}`, minor
  version `75`.
- `get()` auto-recovers from a `401` by forcing one token refresh and retrying.

### Token rotation (the part that surprises people)

Intuit **issues a new refresh token every time you refresh**, and the old one
eventually stops working. So after each company is processed, `qb_main` calls
`rotate_secret()`, which runs:

```
gh secret set QB_<COMPANY>_REFRESH_TOKEN --body <new_token>
```

This requires the `gh` CLI (present on GitHub's `ubuntu-latest` runners) and a
`GH_TOKEN` / `GH_PAT` with permission to write repository secrets. If rotation
fails it only logs a warning — the old refresh token stays valid for ~100 days,
so you have a wide window to fix it before anything breaks.

> **Why this matters:** if you run `qb_main` locally and rotation succeeds, the
> token stored in GitHub Secrets advances and your local `.env` token becomes
> stale. Keep that in mind when testing locally.

## What it pulls — `qb_reports.py`

Two kinds of calls, for each company:

**Reports** (`REPORT_CONFIGS`) — hit `reports/<Name>` with a `date_macro`:

```
ProfitAndLoss, ProfitAndLossDetail, BalanceSheet, BalanceSheetDetail,
CashFlow, GeneralLedger, TrialBalance, TransactionList   → "This Fiscal Year"
                                                            (BalanceSheet → "Today")
AgedReceivableDetail, AgedPayableDetail                  → (no macro)
```

**Entity lists** (`ENTITY_QUERIES`) — via the SQL-like query endpoint:

```
SELECT * FROM Customer / Vendor / Account  MAXRESULTS 1000
```

### Parsing QB report JSON

QB reports are a **recursive tree**, not a flat table: `Section` rows contain
nested `Rows` and an optional `Summary`; `Data` rows contain `ColData`.
`_parse_rows()` walks this tree and flattens it to a list of flat dicts, tagging
each with `Company`, `Section`, and `Row_Type` (`Data` or `Total`). Column
titles come from the report's `Columns` block (with de-duplication for repeated
titles). `fetch_report` also injects `Report_Period` and `Report_Basis` from the
report header. Entity lists are flattened with plain `json_normalize`.

## Assembling the files — `qb_main.py`

For each report/entity, the per-company DataFrames are collected into a list and
**concatenated** into one file (`write_excel` → `pd.concat`). So
`QB_ProfitAndLoss.xlsx` contains all companies' P&L stacked, distinguishable by
the `Company` column — exactly what Power BI needs to slice by entity. Entity
files get a trailing `s` (e.g. `QB_Customers.xlsx`). Empty results are skipped.

## Upload — `qb_onedrive_upload.py`

Globs `QB_*.xlsx` from `QB_OUTPUT_DIR` and uploads each to **OneDrive/QuickBooks/**
using the shared Graph helpers. See [onedrive-and-alerts.md](./onedrive-and-alerts.md).

## Common tasks

- **Onboard N&J Trailers / Properties** → add the company's realm ID
  (`QB_NJ_*_REALM_ID`) and `QB_NJ_*_REFRESH_TOKEN` as secrets; the loop picks
  them up automatically. See the onboarding checklist in
  [operations.md](./operations.md).
- **A company is being skipped** → it's missing either its token or its realm
  ID; check the `Skipping <company> (no credentials)` log line.
- **Refresh-token errors after local testing** → you probably rotated the token
  locally; pull the latest value from GitHub Secrets, or always test against a
  throwaway token.
