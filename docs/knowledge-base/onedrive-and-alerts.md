# Shared layer: OneDrive upload, Microsoft Graph & the Azure app

All three connectors end the same way: push their Excel output to OneDrive so
Power BI can read it. That upload logic lives in **one** place,
`onedrive_upload.py`, and everything else reuses it. The same Azure app
registration also powers the Samsara email alerts.

## The Azure app registration

There is **one** Microsoft Entra (Azure AD) app registration behind all Graph
calls. It uses the OAuth2 **client-credentials** flow (app-only, no user
sign-in) and needs these **Application** permissions, with admin consent:

| Permission | Used by | For |
|------------|---------|-----|
| `Files.ReadWrite.All` | all uploads | writing files into a user's OneDrive |
| `Mail.Send` | `samsara_alerts.py` | sending the fleet alert email |

The three credentials (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
`AZURE_CLIENT_SECRET`) are shared by every job. Token endpoint:
`https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` with
`scope=https://graph.microsoft.com/.default`.

> Because it's app-only with `Files.ReadWrite.All`, the app can write to **any**
> user's OneDrive — which is why uploads target a specific user by UPN
> (`ONEDRIVE_USER_UPN`, currently `jeff@xfreight.net`) rather than "me."

## `onedrive_upload.py` — the shared helpers

Three functions are imported by the Samsara and QB upload scripts:

- **`get_token(tenant, client, secret)`** — client-credentials token for Graph.
  (Also reused by `samsara_alerts.py`.)
- **`ensure_folder(token, user_upn, folder_path)`** — creates the destination
  folder (and intermediate folders) if missing; treats "already exists" as fine.
- **`upload_file(token, user_upn, folder_path, filename, file_path)`** — uploads
  via a **resumable upload session** in 10 MiB chunks (works for any file size),
  with `@microsoft.graph.conflictBehavior: replace` so each run overwrites the
  previous file. Path segments are URL-encoded so spaces work.

Running `python -m src.onedrive_upload` directly uploads the Alvys file using
its own `main()`.

## Where each file lands in OneDrive

| Connector | Upload script | OneDrive location | Filename written |
|-----------|---------------|-------------------|------------------|
| Alvys | `src.onedrive_upload` | root (`ONEDRIVE_FOLDER_PATH=""`) | `Alvys Pipeline.xlsx` * |
| Samsara | `src.samsara_onedrive_upload` | `/Samsara` | `Samsara Master.xlsx` |
| QuickBooks | `src.qb_onedrive_upload` | `/QuickBooks` | each `QB_*.xlsx` |

\* The Alvys filename is configurable via `ONEDRIVE_TARGET_FILENAME` (defaults to
`Alvys_Master.xlsx` in code; the workflow sets it to `Alvys Pipeline.xlsx`). The
local file is always written as `Alvys_Master.xlsx`; the OneDrive copy uses the
configured name. **Do not point this at `Alvys Master 2026.xlsx`** — that is the
hand-maintained workbook the Power BI report reads, and the upload uses
`conflictBehavior: replace`, so a shared name overwrites the manual file. The
daily scorecard email reads `Alvys Master 2026.xlsx` directly, not the pipeline
upload.

## Environment variables for the upload layer

| Variable | Required | Used by | Notes |
|----------|----------|---------|-------|
| `AZURE_TENANT_ID` | ✅ | all Graph calls | tenant GUID |
| `AZURE_CLIENT_ID` | ✅ | all Graph calls | app registration GUID |
| `AZURE_CLIENT_SECRET` | ✅ | all Graph calls | app secret value |
| `ONEDRIVE_USER_UPN` | ✅ | all uploads | whose OneDrive (e.g. `jeff@xfreight.net`) |
| `ONEDRIVE_FOLDER_PATH` | optional | Alvys only | target folder; `""` = root |
| `ONEDRIVE_TARGET_FILENAME` | optional | Alvys only | default `Alvys_Master.xlsx` |
| `OUTPUT_DIR` / `SAMSARA_OUTPUT_DIR` / `QB_OUTPUT_DIR` | optional | respective uploads | where to find the local file(s) |

## Why a resumable upload session for small files?

Graph's simple `PUT …/content` upload caps at 4 MiB. Rather than branch on size,
the code **always** uses an upload session — it's a couple extra requests but
removes a whole class of "file got bigger than 4 MiB and broke" failures. Simple
and uniform beats clever here.

## Failure modes

- **401 from the token endpoint** → bad/expired `AZURE_CLIENT_SECRET`, or the
  tenant/client IDs are wrong.
- **403 on upload** → the app is missing `Files.ReadWrite.All` consent, or the
  target `ONEDRIVE_USER_UPN` doesn't have a provisioned OneDrive.
- **Alerts never send but uploads work** → `Mail.Send` consent is missing (it's a
  separate permission from file access).

## Scorecard Alvys KPIs — must mirror the Power BI report

The daily brief's Alvys numbers (revenue, driver rate, margin, mileage, the
per-entity table) are computed in `src/scorecard_email.py` and **must match the
Power BI XFreight Report**, whose measures are defined in
`powerbi/queries/DAX_Measures.dax`. The contract, verified to the dollar against
`Alvys Master 2026.xlsx` for closed months:

- **Read the Loads tab columns directly.** Driver Rate = `SUM(Loads[Driver Rate])`
  and mileage = `SUM(Loads[... Dispatch Mileage])`. The Loads `Driver Rate` column
  already holds each load's *full settled pay* (all its trips aggregated) — do
  **not** reconstruct it by summing the Trips tab (that lands close but not exact)
  and do **not** add `Carrier Rate` (the payout already lives in Driver Rate).
- **Margin = Customer Revenue − Driver Rate.** Margin % = margin ÷ revenue.
- **Group by the `Office` column** (the report's slicer: XFreight / X-Linx /
  X-Trux), not `Invoice As` — they differ for brokered loads invoiced under
  another subsidiary. XFreight + X-Trux are reported as one "X-Trux" line.
- **"Loads" counts every non-cancelled load** in the window, not just
  revenue-bearing ones (matches the report's Loads / Margin-per-Bill).
- Month-to-date is **partial**: late-month loads carry booked revenue before
  driver pay settles, so MTD margin reads high until they close. Only closed
  months are exact.

**Verify before changing this code:** run the offline parity check against a copy
of the workbook and compare to the report's monthly rows —

```bash
python -m src.scorecard_email --check "Alvys Master 2026.xlsx"
```

and run the contract tests: `python tests/test_scorecard_alvys.py`. A missing or
renamed Loads column makes the KPI code silently read `$0` (→ 100% margin); the
`_alvys_health` checks surface that as a "Data check" banner on the email and a
log warning, but the parity check is the real guardrail.
