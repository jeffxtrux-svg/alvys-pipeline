# XFreight OneDrive folder map (seeded 2026-06-05 from OneDrive)

> Source: SharePoint folder search of `XFreight - Claude Working Files`.

This is the canonical organization for all XFreight business documents in OneDrive. The pipeline writes data into a separate set of folders (`API Feeds and Updated XLXS/`, `Samsara/`, `SambaSafety/`, `QuickBooks/`) — see `xfreight-onedrive-and-key-files.md` for that side. This page covers the **business document tree.**

## Top-level structure

```
jeff@xfreight.net OneDrive
└── XFreight - Claude Working Files/
    ├── 01 - Fuel Reports/
    │   └── Archive/
    ├── 02 - Power BI/
    ├── 03 - Finance/
    │   ├── Factoring/
    │   ├── Financials/
    │   ├── Insurance/
    │   ├── JW Logistics Legal/    (dispute-era docs)
    │   ├── Misc/
    │   ├── Payables/
    │   └── Receivables/
    ├── 04 - Brokerage X-Linx/
    ├── 05 - Recruiting & OO/
    ├── 06 - Safety & Compliance/
    │   ├── DOT/
    │   └── Drivers/
    │       └── {Per-Driver-Name}/   (one folder per driver)
    ├── 07 - Operations/
    ├── 08 - Sales/
    │   ├── Call List and Logs/
    │   └── Customers/
    │       ├── AGCO Bid/   (active RFP)
    │       ├── Billion Auto/
    │       ├── JW Logistics/
    │       └── Textron/    (legacy 2023 bid)
    ├── 09 - X-Trux/         (X-Trux-specific operations)
    └── 10 - Misc Files/
```

## Key files in each top-level

### 02 - Power BI
- `XFreight Data.xlsx` — combined Alvys/QB/Samsara feed (legacy, pre-pipeline)
- `X-Linx PBI.xlsx` / `X-Linx PBIV1.xlsx` — brokerage Power BI source workbooks

### 03 - Finance/Financials
- `Goals and Trends/Goals and Trends.xlsx` — Jeff's master goals worksheet
- `Goals and Trends/My Goals worksheet.xlsx` — margin / RPM goal targets ($2.33 RPM, 18% margin, 30% brokerage)
- `Goals and Trends/XFreight Goals.xlsx` — per-driver weekly + monthly mileage goals (2800/11200)
- `Profit and Loss/2025 Profit and Loss.xlsx` — all 5 companies side-by-side, monthly
- `Profit and Loss/2026 Profit and Loss.xlsx` — same, current year
- `1st Qurter 2026/2026 Profit and Loss.xlsx` — Q1 2026 quarterly view
- `Profit and Loss/Performa/X-Freight Performa V2.xlsx` — pro forma w/ SBA 504 cash injection notes ($230K cash, $180K SBA required)
- `Cash Flow/XFreight Cash Flow.xlsx` — multi-year cash flow analysis (2023-2025)
- `Cash Flow/XFreight Cash Flow copy.xlsx` — working version of above

### 03 - Finance/Insurance
- `X-Trux Ins/Acrisure/X-Trux Acrisure Reconciliation v3 42826.xlsx` — Acrisure ↔ check register monthly reconciliation
- `Final Insurancee.xlsx` — X-Trux Payments 2025 register (Acrisure Midwest Trust as payee)

### 03 - Finance/Factoring
- `Factoring Companies.xlsx` — Pathward / Triumph / OTR / eCapital comparison
- `Understanding Factoring in Alvys | Help Center.pdf` — Alvys's how-to

### 03 - Finance/JW Logistics Legal
- `Summary-Invoice-S1000067.pdf` — X-Linx → JWL invoice (12/5/2024)
- Other dispute / legal docs

### 04 - Brokerage X-Linx
- `Broker Agreement-1711129517.pdf` — older X-Trux/XFreight broker agreement template
- `Co-Brokering Agreement.docx` — current template (X-Linx + ABT Brokerage)
- `export-700.xlsx` — Alvys export of last 700 loads
- `carrier.xlsx` — carrier-side load reference

### 05 - Recruiting & OO
- `XTRUX Owner Operator.docx` — recruiting one-pager ($1.89/mi, etc.)
- `XFreight Presentation.pdf` — customer-facing sales deck (40 trailers, 25 OTR power units, ELDs, EDI)

### 06 - Safety & Compliance/Drivers/{Driver Name}/
One folder per driver. Each contains:
- `{Driver Name}.docx` — rate agreement / lease loan template
- (potentially) MVR copies, medical card images, equipment lease docs

Example: `06 - Safety & Compliance/Drivers/Lacey Campbell/Lacey Campbell.docx`

### 06 - Safety & Compliance/DOT
- DOT compliance files (MCMIS Carrier Safety Profile etc.)
- `COMP841776_jb0257_428202610853.pdf` lives in JB's OneDrive Teams Chat files but the canonical home would be here

### 08 - Sales/Customers/{Customer Name}/
- One folder per customer with rate agreement docx + supporting RFP / NDA correspondence

### 08 - Sales/Call List and Logs
- `Call Log.xlsx` — sales pipeline (Customer Name / Email / Phone / Stage / Notes / Followup Date)
- `Leads List.xlsx` — prospect database with MC# / DOT# / Type / Status / Shipping Hours

## OneDrive accounts in play

| Account | OneDrive root |
|---|---|
| jeff@xfreight.net | Primary — all `XFreight - Claude Working Files/` lives here + `QuickBooks/` and `API Feeds and Updated XLXS/` |
| jbsweere@xfreight.net | Secondary — contains `aalinxpacket.pdf`, `Dispatch.xlsx`, some legacy files + `Microsoft Teams Chat Files/` |
| jb@xfreight.net | (recently added to scorecard recipients; OneDrive scope TBD) |

## SharePoint sites (separate from OneDrive personal)

- `xfreightnet.sharepoint.com/sites/DispatchFiles/` — dispatch team shared site
  - `Shared Documents/equipnow10.xlsx` — daily equipment grid
  - `Shared Documents/Alvys Settlements/` — weekly settlement worksheets (e.g. `baSettlmentWorksheek06032026.xlsx`)
