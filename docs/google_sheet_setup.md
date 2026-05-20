# Google Sheet KPI combiner — one-time setup

This wires up `src/gsheet_combine.py` and `.github/workflows/gsheet_combine.yml`
so a single Google Sheet ("X-Freight KPI Dashboard") gets rebuilt 3x/day
from the xlsx files that the Alvys / QuickBooks / Samsara workflows already
push to OneDrive.

You'll do this once. After that, runs are fully automated.

## 1. Create a Google Cloud service account (≈ 5 min)

1. Go to https://console.cloud.google.com — sign in as your X-Freight Google user.
2. Top bar → project dropdown → **New Project** → name it `xfreight-kpi`. Create.
3. Make sure that project is selected.
4. Left menu → **APIs & Services** → **Library**.
   - Search **Google Sheets API** → click it → **Enable**.
   - Search **Google Drive API** → click it → **Enable**.
5. Left menu → **IAM & Admin** → **Service Accounts** → **+ Create service account**.
   - Name: `xfreight-pipeline`. Create and continue. Skip the optional steps. Done.
6. Click the new service account row → **Keys** tab → **Add key** → **Create new key** → **JSON**.
   A JSON file downloads. Keep it — that's the credential.

## 2. Add the credential to GitHub

1. Open the downloaded JSON file in a text editor and copy its **entire** contents.
2. In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.
   - Name: `GOOGLE_SERVICE_ACCOUNT_JSON`
   - Value: paste the JSON contents (it's fine on one line or multi-line)
   - Save.

## 3. Confirm OneDrive read permission

The same Azure app registration that uploads files needs `Files.Read.All`
(Application) permission to read them back. Most likely it already has
`Files.ReadWrite.All`, which covers reading too — no action needed.

If reads fail with 403 at run time, go to **Entra → App registrations →
alvys-pipeline → API permissions** and add `Files.Read.All` (Application),
then click **Grant admin consent**.

## 4. First run — let the workflow create the sheet

1. Push this branch to GitHub. Merge or run from the branch.
2. **Actions tab → "Combine reports to Google Sheet" → Run workflow**.
3. When it finishes, open the log. Look for:
   ```
   NEW SHEET CREATED
     ID:  1Abc...xyz
     URL: https://docs.google.com/spreadsheets/d/1Abc...xyz/edit
   ```
4. The sheet is shared with `jeff@xfreight.net` (configurable via `GOOGLE_SHARE_WITH`).
   Open it from your inbox notification or the URL above.

## 5. Wire the sheet ID back into the workflow

1. Copy the ID printed in the log.
2. **Settings → Secrets and variables → Actions → Variables tab → New repository variable**.
   - Name: `GOOGLE_SHEET_ID`
   - Value: paste the ID (no quotes)
   - Save.

## 6. Run it again — this time the data lands

Trigger the workflow once more from the Actions tab. This run:
1. Downloads xlsx files from OneDrive root + `/QuickBooks` + `/Samsara`.
2. Reads every sheet and pushes each to its own tab.
3. Rebuilds the `Dashboard` tab with KPI formulas.
4. Updates the `_Meta` tab with refresh timestamp and per-tab row counts.

From here, the cron in `gsheet_combine.yml` runs it 3x/day automatically.

## How to edit KPIs

The KPI formulas live in one list — `DASHBOARD_KPIS` at the bottom of
`src/gsheet_combine.py`. Each entry is `(Section, Label, Formula)`. The
formulas reference raw tab names like `Alvys_Master_Loads`, `QB_ProfitAndLoss`,
`Samsara_Master_SafetyEvents`. Add or remove rows, push to main, and the next
run rebuilds the Dashboard tab.

If a formula references a tab/column that doesn't exist, the cell shows `—`
instead of breaking — so you can experiment safely.

## Troubleshooting

**`403 The caller does not have permission` from Google**
The service account doesn't have access to that specific sheet. Re-share the
sheet with the service account's email (looks like
`xfreight-pipeline@xfreight-kpi.iam.gserviceaccount.com`) as Editor.

**`Quota exceeded for quota metric 'Write requests'`**
Sheets API limit is 60 writes/min/user. The script already paces at 0.4s
between writes; if you have many tabs (50+), the run takes a few minutes
and may briefly bump quota. The next scheduled run will pick up.

**A tab is missing on the Dashboard**
Open the `_Meta` tab — it lists every tab that was actually pushed in the
last run. Compare against the formula's expected tab name.
