---
title: QuickBooks Integration
type: concept
tags: [technology, quickbooks, accounting, finance]
sources: ["raw/xfreight-quickbooks-integration.md"]
related: ["[[XFreight Entities]]", "[[Data Pipeline Architecture]]", "[[OneDrive]]", "[[Financial Performance]]", "[[SBA 504 Financing]]"]
---

# QuickBooks Integration

XFreight uses five separate QuickBooks Online company files (one per entity). The pipeline pulls accounting reports from the three live companies on every run, with the unusual feature that the OAuth refresh token **rotates on every API call** and must be saved back to GitHub Secrets.

## Summary

Three companies are live in the pipeline (X-Trux, X-Linx, Truk-Way); two are dormant (N&J Trailers, N&J Properties). The QB connector pulls P&L, AR/AP aging, vendor lists, and other reports, flattens the tree-structured JSON with a recursive parser, and writes one `.xlsx` per report to OneDrive. The refresh-token rotation is the only write-back anywhere in the pipeline.

## Key Ideas

- **QB refresh tokens rotate on every run** — the pipeline saves the new token back to GitHub Secrets via `gh secret set` using `GH_PAT`. If `GH_PAT` is absent, the run still works but the old token expires in ~100 days.
- **Recursive parser** — QB report JSON is a tree of `Section`/`Data`/`Summary` rows; `pandas.json_normalize` would lose section labels needed for customer/bucket columns.
- **Five entities, three live** — adding a new company = update `_companies()` in `src/qb_main.py`.
- **AR aging AR exclusion** — all five AR buckets route through `_is_ar_excluded()` to drop JW Logistics.

## Five QB Company Files

| Company | Status | Realm ID source |
|---|---|---|
| X-Trux, Inc. | **Live** | Hardcoded in `_companies()` |
| X-Linx, Inc. | **Live** | Hardcoded |
| Truk-Way Leasing, LLC | **Live** | Hardcoded |
| N&J Trailers | **Not live** | Env: `QB_NJ_TRAILERS_REALM_ID` |
| N&J Properties, LLC | **Not live** | Env: `QB_NJ_PROPERTIES_REALM_ID` |

The N&J entities go live once refresh tokens are seeded (expected after [[SBA 504 Financing]] closes).

## Refresh Token Rotation

The unusual part of the QB connector:

1. Every API call returns a new refresh token.
2. `src/qb_client.py` reads the new token from the response.
3. `qb_refresh.yml` calls `gh secret set QB_XTRUX_REFRESH_TOKEN <new_token>` (and same for X-Linx, Truk-Way) using `GH_PAT`.
4. The next run reads the new token from GitHub Secrets.

If `GH_PAT` is absent: run logs a warning but proceeds. Old token valid for ~100 days. **Don't let this lapse** — once the old token expires, the pipeline can't fetch QB data until manual re-auth.

## Required Secrets

```
QB_CLIENT_ID
QB_CLIENT_SECRET
QB_XTRUX_REFRESH_TOKEN
QB_TRUKWAY_REFRESH_TOKEN
QB_XLINX_REFRESH_TOKEN
QB_NJ_TRAILERS_REFRESH_TOKEN     (add when N&J Trailers goes live)
QB_NJ_PROPERTIES_REFRESH_TOKEN   (add when N&J Properties goes live)
GH_PAT                           (PAT with repo scope — for token rotation)
```

## What Gets Pulled

Per live company, `src/qb_main.py` calls QB Reports API for:

- **ProfitAndLoss** → rate-per-mile cost-out overhead leg + page-1 entity P&L.
- **ARAgingDetail** → page-1 AR tiles + pages 11/12/13 AR sections.
- **APAgingDetail** → AR/AP trend chart.
- **VendorList** → page-1 AP side.
- Additional reports (CashFlow, TrialBalance, GeneralLedger, TransactionList, ProfitAndLossDetail, Accounts, Customers).

All five companies write to `OneDrive/QuickBooks/QB_*.xlsx` (one workbook per report type, all companies merged).

## Recursive Parser

QB report JSON structure:
```json
{"Rows": {"Row": [
  {"type": "Section", "Header": {...}, "Rows": {...}},
  {"type": "Data", "ColData": [...]},
  {"type": "Summary", "ColData": [...]}
]}}
```

The recursive parser in `src/qb_main.py` walks this tree, preserving section labels (customer names, bucket labels) that json_normalize would discard. Each leaf row becomes a DataFrame row with its section context.

## QB ↔ Alvys Invoice Matching

The bill-by-bill reconciliation (page 13) matches Alvys invoice/load numbers to QB invoice `Num` values. QB convention: **`"T" + load number`** (e.g. Alvys load #12345 → QB invoice `T12345`). The matcher uses `_norm_inv()` to strip the leading alpha prefix.

## AR Aging Buckets

Standard buckets used throughout the brief:

| Bucket | Days | Status |
|---|---|---|
| Current | Not yet due | OK |
| 1–30 | Past due | Warn |
| 31–60 | Past due | Escalate |
| 61–90 | Past due | Escalate (bad) |
| 91+ | Past due | Collections |

`_is_ar_excluded()` drops JW Logistics from all five buckets in every aggregation.

## Adding a New QB Company

1. Add it to `_companies()` in `src/qb_main.py` — either hardcode realm ID or read from env.
2. Set up OAuth token in QuickBooks Developer and seed the refresh token into GitHub Secrets.
3. Add the secret name to the `env:` block in `qb_refresh.yml`.
4. On next run, the pipeline pulls the new company's data automatically.

## Connections

- [[XFreight Entities]] — five QB companies map 1:1 to five entities.
- [[Data Pipeline Architecture]] — the QB connector is one of four pulls.
- [[OneDrive]] — QB files land in `OneDrive/QuickBooks/`.
- [[Financial Performance]] — P&L data feeds the brief's entity tiles.
- [[SBA 504 Financing]] — N&J entities go live post-closing.
- [[JW Logistics]] — `_is_ar_excluded()` enforces the exclusion on every AR bucket.
- [[Rate-Per-Mile Goal]] — overhead leg = QB Total Expenses ÷ YTD X-Trux miles.

## Sources

- `raw/xfreight-quickbooks-integration.md`
