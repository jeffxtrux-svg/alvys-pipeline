# XFreight QuickBooks integration (seeded 2026-06-05 from repo)

> Source: `docs/knowledge-base/connector-quickbooks.md`, `src/qb_main.py`
> (`_companies()`), `src/qb_client.py`, `.github/workflows/qb_refresh.yml`.

## Five separate QuickBooks Online company files

| Company | Realm ID | Status | Notes |
|---|---|---|---|
| X-Trux, Inc. | hardcoded in `_companies()` | Live | Asset trucking carrier |
| X-Linx, Inc. | hardcoded | Live | Brokerage |
| Truk-Way Leasing | hardcoded | Live | Per-truck P&L tab on Google Sheets dashboard |
| N&J Trailers | env: `QB_NJ_TRAILERS_REALM_ID` | Not live | Skipped until refresh token exists |
| N&J Properties | env: `QB_NJ_PROPERTIES_REALM_ID` | Not live | Same |

Adding a new company means adding it to `_companies()` in `src/qb_main.py` (or wiring up the N&J env vars).

## Refresh token rotation (the unusual part)

QuickBooks Online's OAuth requires the **refresh token to rotate on every API call**. The new refresh token comes back in the response and must be saved or you're locked out.

- The pipeline writes the rotated tokens **back into GitHub Secrets** via `gh secret set`, using a personal access token in `GH_PAT` (mapped to `GH_TOKEN` env in the workflow).
- If `GH_PAT` is missing, the rotation logs a warning but the run still works — the OLD refresh token stays valid for ~100 days before expiring.
- This is the **only** thing in the entire pipeline that writes back to a source system. Everything else is read-only.

## Secrets required

```
QB_CLIENT_ID
QB_CLIENT_SECRET
QB_XTRUX_REFRESH_TOKEN
QB_TRUKWAY_REFRESH_TOKEN
QB_XLINX_REFRESH_TOKEN
QB_NJ_TRAILERS_REFRESH_TOKEN     (add when N&J Trailers goes live)
QB_NJ_PROPERTIES_REFRESH_TOKEN   (add when N&J Properties goes live)
GH_PAT                            (PAT with repo scope for token rotation)
```

## What gets pulled

`src/qb_main.py` orchestrates a set of QB Reports API calls per live company:

- ProfitAndLoss (used for the rate-per-mile cost-out + page-1 entity P&L)
- ARAgingDetail (used for the page-1 AR tiles + page 11/12/13 AR sections)
- APAgingDetail (used for the AR/AP trend chart)
- VendorList
- a handful of others

Each report's JSON is a **tree of nested `Section`/`Data`/`Summary` rows**. The parser in `src/qb_main.py` walks that tree recursively, flattening it into rows.

## Why recursive parsing instead of pandas

The Alvys + Samsara connectors flatten via `pandas.json_normalize` because their responses are arrays of records. QuickBooks reports are hierarchical (section → subsection → row), and json_normalize doesn't preserve the section labels that turn into the "Customer" column or the "Bucket" column. The recursive parser does.

## QB ↔ Alvys invoice matching

The bill-by-bill reconciliation on page 13 matches Alvys invoice / load numbers to QB invoice `Num` values. QuickBooks uses a convention of `"T" + load number` for invoice numbers (e.g. Alvys load #12345 becomes QB invoice `T12345`). The matcher uses `_norm_inv` to strip a leading alpha prefix so the two sides match correctly.

## AR aging buckets

Standard buckets used everywhere in the brief:

- **Current** — not yet due (mute pill, "not overdue")
- **1–30 days** past due (warn, "past due")
- **31–60 days** (warn, "escalate")
- **61–90 days** (bad, "escalate")
- **91+ days** (bad, "collections")

Computed from `due date` vs today. `_is_ar_excluded()` drops JW Logistics from all five buckets.
