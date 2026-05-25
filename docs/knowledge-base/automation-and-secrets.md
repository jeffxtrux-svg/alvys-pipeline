# Automation & secrets

This page covers how the pipeline runs unattended (GitHub Actions) and the
complete list of every secret and environment variable it consumes.

## The three workflows

Each connector has its own workflow in `.github/workflows/`. All three:

- trigger on **`workflow_dispatch`** (manual "Run workflow" button) **and** a
  **cron schedule (3×/day)**;
- run on `ubuntu-latest`, Python 3.11, `pip install -r requirements.txt`;
- finish by uploading the `output/` folder as a **workflow artifact**
  (`if: always()`, 7-day retention) — so you can download results from the
  Actions tab even if the OneDrive step failed.

| Workflow file | Steps | Cron (UTC) |
|---------------|-------|------------|
| `refresh.yml` (Alvys) | pull → OneDrive upload → artifact | `0 12,18,0 * * *` |
| `samsara_refresh.yml` | pull → OneDrive upload → **alerts** → artifact | `0 12,18,0 * * *` |
| `qb_refresh.yml` | pull (+token rotation) → OneDrive upload → artifact | `30 12,18,0 * * *` |
| `scorecard_email.yml` | read OneDrive files → compute KPIs → email daily scorecard | `0 13 * * *` (1×/day) |

The cron times map to roughly **6am / 12pm / 6pm Central**. QuickBooks is offset
30 minutes to avoid overlapping with the Alvys/Samsara runs. (Cron is fixed UTC,
so the Central clock time shifts by an hour across daylight-saving changes.)

### Per-workflow notable env wiring

- **Alvys** pins `ALVYS_START_DATE: '2024-01-01'` and sets
  `ONEDRIVE_TARGET_FILENAME: "Alvys Master.xlsx"` (space, to match Power BI) with
  `ONEDRIVE_FOLDER_PATH: ""` (OneDrive root).
- **Samsara** sets `SAMSARA_DAYS_BACK: '90'` and `SAMSARA_SAFETY_DAYS_BACK: '190'`
  and runs the alerts step with `ALERT_FROM_UPN: jeff@xfreight.net` +
  `ALERT_TO_EMAILS` from secrets.
- **QuickBooks** passes `GH_TOKEN: ${{ secrets.GH_PAT }}` so `gh secret set` can
  rotate refresh tokens, and leaves `QB_NJ_*_REALM_ID` empty until those
  companies are onboarded.

`ONEDRIVE_USER_UPN: jeff@xfreight.net` is hardcoded in all three workflows.

## Complete environment-variable / secret reference

Anything marked **secret** must be stored in *Settings → Secrets and variables →
Actions* in GitHub (and in a local `.env` for local runs). Non-secret values are
set inline in the workflow YAML.

### Alvys (`src.main`)

| Variable | Secret? | Required | Default | Purpose |
|----------|---------|----------|---------|---------|
| `ALVYS_CLIENT_ID` | ✅ | ✅ | — | Alvys API client id |
| `ALVYS_CLIENT_SECRET` | ✅ | ✅ | — | Alvys API client secret |
| `ALVYS_START_DATE` | — | — | today − 425d | how far back to pull (`YYYY-MM-DD`) |
| `OUTPUT_DIR` | — | — | `output` | where the xlsx is written |
| `DEBUG_DIR` | — | — | `output/_debug` | sample-JSON dump location |
| `ALVYS_OFFICE_MAPPINGS` | — | — | — | JSON override of office ID → name |

### Samsara (`src.samsara_main`, `src.samsara_alerts`)

| Variable | Secret? | Required | Default | Purpose |
|----------|---------|----------|---------|---------|
| `SAMSARA_API_TOKEN` | ✅ | ✅ | — | Samsara API token |
| `SAMSARA_DAYS_BACK` | — | — | `90` | trips window |
| `SAMSARA_SAFETY_DAYS_BACK` | — | — | `190` | safety / DVIR / HOS-violation window (covers "previous 6 months") |
| `SAMSARA_OUTPUT_DIR` | — | — | `output/samsara` | output location |
| `ALERT_FROM_UPN` | — | — | `jeff@xfreight.net` | mailbox to send alerts from |
| `ALERT_TO_EMAILS` | ✅ | — | = `ALERT_FROM_UPN` | comma-separated recipients |

### QuickBooks (`src.qb_main`)

| Variable | Secret? | Required | Default | Purpose |
|----------|---------|----------|---------|---------|
| `QB_CLIENT_ID` | ✅ | ✅ | — | Intuit app client id |
| `QB_CLIENT_SECRET` | ✅ | ✅ | — | Intuit app client secret |
| `QB_XTRUX_REFRESH_TOKEN` | ✅ | ✅ | — | X-Trux refresh token (rotates) |
| `QB_TRUKWAY_REFRESH_TOKEN` | ✅ | ✅ | — | Truk-Way refresh token (rotates) |
| `QB_XLINX_REFRESH_TOKEN` | ✅ | ✅ | — | X-Linx refresh token (rotates) |
| `QB_NJ_TRAILERS_REFRESH_TOKEN` | ✅ | — | — | add when onboarded |
| `QB_NJ_PROPERTIES_REFRESH_TOKEN` | ✅ | — | — | add when onboarded |
| `QB_NJ_TRAILERS_REALM_ID` | — | — | `""` | N&J Trailers company id |
| `QB_NJ_PROPERTIES_REALM_ID` | — | — | `""` | N&J Properties company id |
| `QB_OUTPUT_DIR` | — | — | `output/quickbooks` | output location |
| `GH_PAT` → `GH_TOKEN` | ✅ | ✅* | — | PAT for `gh secret set` token rotation |

\* Required only for the rotation step to succeed; the run still produces data
without it (it just logs a warning and the old token keeps working ~100 days).

### Shared — Microsoft Graph / OneDrive

| Variable | Secret? | Required | Purpose |
|----------|---------|----------|---------|
| `AZURE_TENANT_ID` | ✅ | ✅ | tenant GUID |
| `AZURE_CLIENT_ID` | ✅ | ✅ | app registration GUID |
| `AZURE_CLIENT_SECRET` | ✅ | ✅ | app secret |
| `ONEDRIVE_USER_UPN` | — | ✅ | target OneDrive owner |
| `ONEDRIVE_FOLDER_PATH` | — | — | Alvys destination folder (`""` = root) |
| `ONEDRIVE_TARGET_FILENAME` | — | — | Alvys filename override |

> **Local runs:** `.env.example` documents every variable above — copy it to
> `.env` and fill in real values. The QuickBooks and Microsoft Graph / OneDrive
> blocks are required for those connectors and their uploads.

## Enabling / disabling the schedule

The `schedule:` blocks are **active** in all three workflows. To pause a
connector, comment out its `schedule:` block (manual `workflow_dispatch` still
works) or disable the workflow from the Actions tab. To change frequency, edit
the cron lines — remember they're UTC.

## Cost

Private-repo GitHub Actions includes 2,000 free minutes/month. Each run is a few
minutes, so 3×/day across three workflows stays well within the free tier.
