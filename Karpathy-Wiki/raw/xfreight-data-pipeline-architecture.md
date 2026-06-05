# XFreight data pipeline architecture (seeded 2026-06-05 from repo)

> Source: `CLAUDE.md` (top-level overview), `docs/knowledge-base/architecture.md`,
> `docs/knowledge-base/README.md`.

## The problem

XFreight runs on three SaaS systems that don't talk to each other:

- **Alvys** — the TMS (transportation management system): loads, trips, fuel, drivers, trucks, trailers, invoices.
- **Samsara** — telematics: where the trucks are, how they're driven, safety events, HOS violations, DVIR defects, driver safety scores, IFTA.
- **QuickBooks Online** — accounting, kept in five separate company files (X-Trux, X-Linx, Truk-Way, plus two future N&J entities).
- **SambaSafety** — added later as a fourth source: MVR risk index, license expirations, FMCSA CSA scorecard.

The business wants **one set of Power BI dashboards** spanning all of them, plus a daily executive brief by email.

## The shape of the solution

```
Alvys API ───┐
Samsara API ─┤     pull (Python in GitHub Actions, on cron)
QB API ──────┤            │
SambaSafety ─┘            ▼
                    Normalize to .xlsx
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
        OneDrive (Excel)        Google Sheets KPI dashboard
              │                       │
              ▼                       ▼
        Power BI report         (read by anyone with the link)
              │
              ▼
       Daily scorecard email (5am CT, 13 pages PDF)
```

## Design principles baked into the code

- **Fail soft on optional data.** Reference-data fetches and whole reports are wrapped in try/except so one 404 or one bad company doesn't kill the run — missing data becomes blank columns, not a crash.
- **Endpoint discovery by fallback.** Several fetchers try a list of candidate paths/filters and keep the first that works (Alvys `_fetch_with_fallback`, Samsara path lists).
- **Idempotent & read-only.** A run fully rewrites its output and uploads with `replace`; re-running is always safe. Nothing is ever written back to Alvys/Samsara/QB — the only write-back anywhere is the rotated QuickBooks refresh token saved into GitHub Secrets.
- **Verbose, structured logging** at every step (page counts, running totals).

## Why Excel-in-OneDrive (not a database)?

A database would be the "proper" answer, but it adds hosting, credentials, backups, and a gateway for Power BI. Excel-in-OneDrive was chosen because:

- Power BI connects to OneDrive/SharePoint files **with no on-prem gateway**.
- The business already had a hand-maintained `Alvys_Master.xlsx`; matching its schema let the existing Power BI report keep working with zero rebuild.
- It's debuggable by a non-engineer — you can open the file and look.

The tradeoff (file locks, the awkward "iterate pipeline then refresh" loop) is accepted.

## The shared four-step pattern

Every connector follows the same skeleton — learn it once, the rest follow:

1. **PULL** — a client class (`AlvysClient`, `SamsaraClient`, `QBClient`, `SambaSafetyClient`) owns auth + pagination and exposes `fetch_*` methods returning `list[dict]` of raw JSON.
2. **TRANSFORM** — JSON → rows. Three different approaches:
   - **Alvys** is declarative: `src/column_mappings.py` is a large list of `(excel_column_name, accessor)` tuples. Exists to match the legacy 200-column `Alvys_Master.xlsx` schema for the Power BI report.
   - **Samsara** uses `pandas.json_normalize` (sheets are new, no legacy schema).
   - **QuickBooks** uses a recursive parser because QB report JSON is a tree of nested `Section`/`Data`/`Summary` rows.
3. **WRITE** — rows → `.xlsx`.
4. **UPLOAD** — `.xlsx` → OneDrive. All connectors share one module, `src/onedrive_upload.py` (Microsoft Graph, one Azure app, client-credentials, resumable upload with `conflictBehavior: replace`).

## Knowledge base in the repo

- `docs/knowledge-base/README.md` — index page.
- `docs/knowledge-base/architecture.md` — the *why*.
- `docs/knowledge-base/operations.md` — debugging recipes + runbook.
- `docs/knowledge-base/automation-and-secrets.md` — every cron, every secret.
- `docs/knowledge-base/connector-*.md` — one file per source (alvys, samsara, quickbooks, sambasafety).
- `docs/knowledge-base/rate-per-mile-goal.md` — the cost-out methodology.
- `docs/knowledge-base/powerbi.md` — a proof-of-concept where Power BI reads the Alvys API directly.
