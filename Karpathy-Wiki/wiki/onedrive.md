---
title: OneDrive
type: concept
tags: [technology, onedrive, files, storage]
sources: ["raw/xfreight-onedrive-and-key-files.md", "raw/xfreight-onedrive-folder-map.md"]
related: ["[[Data Pipeline Architecture]]", "[[Power BI]]", "[[QuickBooks Integration]]", "[[Key People]]"]
---

# OneDrive

Microsoft OneDrive is XFreight's primary file storage and the staging layer for all pipeline outputs. The primary account is `jeff@xfreight.net`.

## Summary

The pipeline writes to `jeff@xfreight.net`'s OneDrive. The `Alvys Master 2026.xlsx` file is hand-maintained and must NEVER be overwritten by the pipeline. The pipeline writes to `Alvys Pipeline.xlsx` instead. All five QB report workbooks, the Samsara master, and the SambaSafety master also land here for consumption by Power BI and the scorecard email.

## Key Ideas

- **Two "Alvys Master" files** — the most critical naming rule in the repo. `Alvys Master 2026.xlsx` = hand-maintained (Power BI reads this). `Alvys Pipeline.xlsx` = pipeline-written. A wrong filename would overwrite the manual file and break Power BI.
- Auth: Microsoft Graph, Azure app (client-credentials), `Files.ReadWrite.All` + `Mail.Send` permissions.
- Upload mode: resumable, `conflictBehavior: replace`. Re-running always safely overwrites.
- Shared upload module: `src/onedrive_upload.py`.

## The Critical Naming Rule

| File | Managed by | Read by | NEVER overwrite? |
|---|---|---|---|
| **`Alvys Master 2026.xlsx`** | Hand-maintained (Jeff) | Power BI + scorecard email | **YES — never let pipeline write here** |
| **`Alvys Pipeline.xlsx`** | Pipeline (`refresh.yml`) | Scorecard debug section | No — pipeline-written |

The CI workflow has `ONEDRIVE_TARGET_FILENAME: "Alvys Pipeline.xlsx"` baked into `refresh.yml`. If this ever changes to `"Alvys Master 2026.xlsx"`, it would break Power BI.

The daily scorecard email reads `Alvys Master 2026.xlsx` (not the pipeline output) so its KPIs match the Power BI report exactly.

## Pipeline Output Files

| Workflow | OneDrive output |
|---|---|
| `refresh.yml` (Alvys) | `Alvys Pipeline.xlsx` at root |
| `samsara_refresh.yml` | `Samsara/Samsara_Master.xlsx` |
| `qb_refresh.yml` | `QuickBooks/QB_*.xlsx` (one per QB report) |
| `sambasafety_refresh.yml` | `SambaSafety/SambaSafety_Master.xlsx` |
| `scorecard_email.yml` | Read-only. Writes only an idempotency marker file. |

## Folder Layout (Pipeline Output + Business Documents)

```
jeff@xfreight.net / OneDrive root
├── Alvys Master 2026.xlsx          ← HAND-MAINTAINED. Do NOT overwrite.
├── Alvys Pipeline.xlsx             ← pipeline-written
├── QuickBooks/
│   ├── QB_ProfitAndLoss.xlsx
│   ├── QB_ARAgingDetail.xlsx
│   ├── QB_APAgingDetail.xlsx
│   ├── QB_VendorList.xlsx
│   └── ... (one workbook per QB report)
├── Samsara/
│   └── Samsara_Master.xlsx
└── SambaSafety/
    ├── risk_index_report.csv       ← landed via Power Automate (or manual)
    ├── violationsReport.csv
    ├── CSA2010 Preview Scorecard.csv   ← optional; page 10 fails soft without it
    └── SambaSafety_Master.xlsx

XFreight - Claude Working Files/    ← business document tree
├── 01 - Fuel Reports/
├── 02 - Power BI/
├── 03 - Finance/
│   ├── Factoring/
│   ├── Financials/  (Goals and Trends.xlsx, P&L workbooks, Performa)
│   ├── Insurance/   (Acrisure reconciliation)
│   ├── JW Logistics Legal/
│   ├── Payables/
│   └── Receivables/
├── 04 - Brokerage X-Linx/
├── 05 - Recruiting & OO/
├── 06 - Safety & Compliance/
│   ├── DOT/
│   └── Drivers/{per-driver folder}
├── 07 - Operations/
├── 08 - Sales/
│   ├── Call List and Logs/
│   └── Customers/{per-customer folder}
├── 09 - X-Trux/
└── 10 - Misc Files/
```

## SambaSafety CSV Landing

Three options for getting `CSA2010 Preview Scorecard.csv` + `risk_index_report.csv` + `violationsReport.csv` into OneDrive:

1. **Manual drop** — open each daily SambaSafety email, save attachments. ~1 min/day; must happen before 2:30am CT for the morning merge.
2. **Power Automate flow (recommended)** — flow watching `jeff@xfreight.net` for SambaSafety mail, auto-saves attachments. Set up once, hands-free.
3. **SambaSafety API** — set `SAMBASAFETY_API_TOKEN`; the refresh job switches to API mode, no CSV step.

## OneDrive Accounts

| Account | Purpose |
|---|---|
| jeff@xfreight.net | **Primary** — all pipeline outputs + `XFreight - Claude Working Files/` |
| jbsweere@xfreight.net | Secondary — `aalinxpacket.pdf`, legacy files, dispatch |
| jb@xfreight.net | Scorecard email recipients (added 2026-06-05) |

## SharePoint (Separate from Personal OneDrive)

- `xfreightnet.sharepoint.com/sites/DispatchFiles/Shared Documents/`
  - `equipnow10.xlsx` — daily equipment grid.
  - `Alvys Settlements/` — weekly settlement worksheets.

## Key Business Documents by Number

| Folder | Key files |
|---|---|
| `03 - Finance/Financials/Goals and Trends/` | `Goals and Trends.xlsx` (Jeff's master), `XFreight Goals.xlsx` (per-driver), `My Goals worksheet.xlsx` |
| `03 - Finance/Financials/Profit and Loss/` | `2025 P&L.xlsx`, `2026 P&L.xlsx`, `Performa/X-Freight Performa V2.xlsx` |
| `03 - Finance/Insurance/X-Trux Ins/Acrisure/` | Reconciliation spreadsheets (see [[Acrisure Dispute]]) |
| `03 - Finance/Factoring/` | Vendor comparison (Pathward/Triumph/OTR/eCapital) |
| `05 - Recruiting & OO/` | `XTRUX Owner Operator.docx`, `XFreight Presentation.pdf` |
| `06 - Safety & Compliance/DOT/` | BASIC snapshot CSVs (Oct 2024, Nov 2025) |
| `08 - Sales/Customers/Billion Auto/` | Rate agreement docx |
| `08 - Sales/Customers/Bids/AGCO Bid/` | RFP docx + response matrix |
| `08 - Sales/Call List and Logs/` | `Call Log.xlsx`, `Leads List.xlsx` |

## Connections

- [[Data Pipeline Architecture]] — pipeline writes here.
- [[Power BI]] — reads `Alvys Master 2026.xlsx`.
- [[QuickBooks Integration]] — QB files in `QuickBooks/` subfolder.
- [[Key People]] — jeff@xfreight.net is the primary OneDrive account.
- [[Acrisure Dispute]] — key files in `03 - Finance/Insurance/`.

## Sources

- `raw/xfreight-onedrive-and-key-files.md`
- `raw/xfreight-onedrive-folder-map.md`
