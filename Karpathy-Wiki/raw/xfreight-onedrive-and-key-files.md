# XFreight OneDrive structure + key files (seeded 2026-06-05 from repo)

> Source: `CLAUDE.md` (configuration section + Power BI naming rule),
> `docs/knowledge-base/onedrive-and-alerts.md`, `src/onedrive_upload.py`,
> per-connector upload scripts.

## The OneDrive account

- **User UPN:** `jeff@xfreight.net` — the OneDrive that hosts all pipeline outputs.
- **Auth:** Microsoft Graph, one Azure app (`AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET`), client-credentials flow, application permissions.
- **Required Graph permissions:** Files.ReadWrite.All, Mail.Send (the latter for the SambaSafety + scorecard email jobs).
- **Single shared upload module:** `src/onedrive_upload.py`. The other upload scripts (`samsara_onedrive_upload.py`, `qb_onedrive_upload.py`) import its `get_token` / `ensure_folder` / `upload_file` helpers.
- **Upload mode:** resumable, `conflictBehavior: replace`. Re-running a pull always safely overwrites.

## Folder layout in OneDrive

```
OneDrive (jeff@xfreight.net)
├── Alvys Master 2026.xlsx              ← HAND-MAINTAINED. Power BI report reads this.
├── Alvys Pipeline.xlsx                 ← pipeline-written. Read by the scorecard / debug only.
├── QuickBooks/
│   ├── QB_ProfitAndLoss.xlsx
│   ├── QB_ARAgingDetail.xlsx
│   ├── QB_APAgingDetail.xlsx
│   ├── QB_VendorList.xlsx
│   └── ... (one workbook per QB report, all companies merged)
├── Samsara/
│   └── Samsara_Master.xlsx             ← pipeline-written. Multi-sheet.
└── SambaSafety/
    ├── risk_index_report.csv           ← landed daily via Power Automate (or manual drop)
    ├── violationsReport.csv            ← same
    ├── CSA2010 Preview Scorecard.csv   ← same (optional — page 10 fails soft without it)
    └── SambaSafety_Master.xlsx         ← pipeline-written, merged from the three CSVs
```

## CRITICAL: the two "Alvys Master" files

This is the most important naming rule in the repo and worth its own page in the wiki:

- **`Alvys Master 2026.xlsx`** — HAND-MAINTAINED. The Power BI report reads this workbook. Do **NOT** let the pipeline write to this filename. The daily scorecard email also reads this file (not the pipeline output) so its KPIs match the Power BI report.
- **`Alvys Pipeline.xlsx`** — pipeline-written. Set via `ONEDRIVE_TARGET_FILENAME` env var in `refresh.yml`. Distinct on purpose. The scorecard's debug section can read this.

If the pipeline ever started writing to `Alvys Master 2026.xlsx`, it would overwrite the manual workbook and break the Power BI report. The CI workflow has `ONEDRIVE_TARGET_FILENAME: "Alvys Pipeline.xlsx"` baked in to prevent this.

## What writes what — connector → file map

| Workflow / connector | OneDrive output |
|---|---|
| `refresh.yml` (Alvys) | `Alvys Pipeline.xlsx` at the root |
| `samsara_refresh.yml` | `Samsara/Samsara_Master.xlsx` |
| `qb_refresh.yml` | `QuickBooks/QB_*.xlsx` (multiple files per QB report) |
| `sambasafety_refresh.yml` | `SambaSafety/SambaSafety_Master.xlsx` (from the three pre-landed CSVs) |
| `scorecard_email.yml` | **Read-only.** Reads `Alvys Master 2026.xlsx` + the QB folder + Samsara_Master + SambaSafety_Master. Emails the rendered PDF. Writes a same-day marker file to OneDrive for the idempotency check. |

## How SambaSafety CSVs get into OneDrive

Three options for landing the source CSVs in `OneDrive/SambaSafety/`:

1. **Manual drop** — open each daily email from `no-reply@sambasafety.com`, save the CSV attachments. ~1 min/day, must happen before 2:30am CT for the morning merge.
2. **Power Automate flow (recommended)** — flow in `flow.microsoft.com` watching `jeff@xfreight.net` for new SambaSafety mail and saving attachments to `OneDrive/SambaSafety/`. Set up once, hands-free forever.
3. **SambaSafety API (live, preferred long-term)** — set `SAMBASAFETY_API_TOKEN` and the refresh job switches to API mode, no CSV step.

## Power BI

The Power BI report reads `Alvys Master 2026.xlsx` directly from OneDrive (no on-prem gateway). This is the entire reason the pipeline writes to Excel-in-OneDrive instead of a database.

The `powerbi/` folder in the repo also holds a proof-of-concept where Power BI reads the Alvys API directly (Power Query `.pq` + DAX measures), bypassing the Excel intermediate. Not yet adopted as the primary flow.
