---
title: Data Pipeline Architecture
type: concept
tags: [pipeline, architecture, technology, automation]
sources: ["raw/xfreight-data-pipeline-architecture.md"]
related: ["[[OneDrive]]", "[[QuickBooks Integration]]", "[[Power BI]]", "[[Daily Schedule]]", "[[Daily Scorecard Email]]"]
---

# Data Pipeline Architecture

The GitHub Actions Python pipeline that pulls from Alvys, Samsara, QuickBooks, and SambaSafety, normalizes to `.xlsx`, and stages data in OneDrive for Power BI and the daily executive brief.

## Summary

Three SaaS systems (Alvys TMS, Samsara telematics, QuickBooks accounting) don't talk to each other. The pipeline pulls from each on a cron schedule, normalizes to Excel in OneDrive, and feeds both Power BI dashboards and a 13-page daily scorecard email. There is no database — Excel-in-OneDrive was chosen to avoid Power BI gateway requirements and to match the legacy file format.

## Key Ideas

- **No database** — Excel-in-OneDrive is the staging layer (Power BI reads OneDrive natively without an on-prem gateway).
- **Fail soft** — one 404 or one bad QB company doesn't kill the run; missing data → blank columns, not crash.
- **Idempotent** — re-running is always safe; `conflictBehavior: replace` on upload.
- **Read-only** — the ONLY write-back to any source system is the rotated QuickBooks refresh token saved into GitHub Secrets.
- Every connector follows the same **four-step skeleton**: Pull → Transform → Write → Upload.

## System Overview

```
Alvys API ─────┐
Samsara API ───┤    GitHub Actions Python (cron)
QuickBooks ────┤           │
SambaSafety ───┘           ▼
                     Normalize to .xlsx
                           │
               ┌───────────┴────────────┐
               ▼                        ▼
         OneDrive (Excel)         Google Sheets KPI
               │                        │
               ▼                        ▼
         Power BI report         (any link holder)
               │
               ▼
        Daily 13-page PDF
        scorecard email (5am CT)
```

## The Four-Step Pattern

Every connector follows the same skeleton:

### 1. PULL
A client class (`AlvysClient`, `SamsaraClient`, `QBClient`, `SambaSafetyClient`) owns auth + pagination and exposes `fetch_*` methods returning `list[dict]` raw JSON.

Auth styles differ:
- **Alvys:** OAuth2 client-credentials (token cached).
- **Samsara:** static bearer token.
- **QuickBooks:** OAuth2 refresh-token that **rotates on every run** (the only write-back in the pipeline).

### 2. TRANSFORM
JSON → rows. Three distinct approaches:
- **Alvys:** Declarative. `src/column_mappings.py` is a large list of `(excel_column_name, accessor)` tuples where an accessor is a dotted path (`"Stops.first.Address.City"`) or callable. Exists to match the legacy 200-column `Alvys_Master.xlsx` schema for Power BI.
- **Samsara:** `pandas.json_normalize` (sheets are new, no legacy schema to match).
- **QuickBooks:** Recursive parser (QB report JSON is a tree of nested `Section`/`Data`/`Summary` rows that json_normalize can't handle).

### 3. WRITE
Rows → `.xlsx`. `src/output_writer.py` is fussy about Alvys output: exact `MM-DD-YYYY` text dates (America/Chicago) and integer ID columns, because Power Query "Changed Type" steps were authored against those exact formats. **Do not change the date format** without updating Power BI.

### 4. UPLOAD
`.xlsx` → OneDrive. All connectors share `src/onedrive_upload.py` (Microsoft Graph, one Azure app, client-credentials, resumable upload with `conflictBehavior: replace`). The other upload scripts import `get_token` / `ensure_folder` / `upload_file` helpers.

## Design Principles

| Principle | Implementation |
|---|---|
| Fail soft | `_safe_get`, per-report try/except, per-QB-company try/except |
| Endpoint discovery | `_fetch_with_fallback` (Alvys), Samsara path-list fallback |
| Idempotent | Full rewrite + replace on every run |
| Read-only | Only QB token write-back; everything else reads only |
| Verbose logging | Page counts, running totals at every step |

## Why Excel-in-OneDrive (Not a Database)

Power BI connects to OneDrive/SharePoint without a self-hosted gateway. A database would require hosting, credentials, backups, and a gateway. The business already had a hand-maintained `Alvys_Master.xlsx`; matching its schema let the existing Power BI report keep working. The file is also debuggable by non-engineers.

Tradeoff: file locks if workbook is open during a write; awkward pipeline-then-refresh-PBI loop. Accepted.

## Connectors and Files

| Connector | Main script | Output file |
|---|---|---|
| Alvys | `src/main.py` | `output/Alvys_Master.xlsx` → OneDrive `Alvys Pipeline.xlsx` |
| Samsara | `src/samsara_main.py` | `output/samsara/Samsara_Master.xlsx` |
| QuickBooks | `src/qb_main.py` | `output/quickbooks/QB_*.xlsx` |
| Sheets | `src/sheets_main.py` | Google Sheets KPI dashboard |
| Scorecard email | `src/scorecard_email.py` | Reads OneDrive; emails PDF |

## Key Code Files

- `src/column_mappings.py` — Alvys 200-column schema.
- `src/transformers.py` — walks the mappings per record.
- `src/output_writer.py` — writes `.xlsx` with exact date format.
- `src/onedrive_upload.py` — shared upload helpers.
- `src/qb_main.py` — `_companies()` defines the five QB entities.
- `src/scorecard_email.py` — all 13-page brief builders + insights.
- `src/scorecard_insights.py` — Bottom Line + escalation logic.

## Documentation in Repo

- `docs/knowledge-base/README.md` — index.
- `docs/knowledge-base/architecture.md` — the why.
- `docs/knowledge-base/operations.md` — debugging recipes + runbook.
- `docs/knowledge-base/automation-and-secrets.md` — every cron, every secret.
- `docs/knowledge-base/connector-*.md` — one per source.
- `docs/knowledge-base/rate-per-mile-goal.md` — cost-out methodology.

## Connections

- [[OneDrive]] — staging layer.
- [[QuickBooks Integration]] — the unusual token rotation detail.
- [[Power BI]] — the consumer of OneDrive files.
- [[Daily Schedule]] — when each job runs.
- [[Daily Scorecard Email]] — the brief is read-only, reads from OneDrive.

## Sources

- `raw/xfreight-data-pipeline-architecture.md`
