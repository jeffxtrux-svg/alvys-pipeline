---
title: Daily Schedule
type: concept
tags: [automation, schedule, github-actions, cron]
sources: ["raw/xfreight-daily-schedule.md", "raw/xfreight-daily-operations-reports.md"]
related: ["[[Data Pipeline Architecture]]", "[[Daily Scorecard Email]]", "[[OneDrive]]"]
---

# Daily Schedule

The year-round automated schedule for all XFreight pipeline jobs, using the dual-cron + CT-hour-gate DST pattern. Central wall-clock times stay constant across DST transitions with no manual edits.

## Summary

Every workflow runs at fixed Central wall-clock times year-round. GitHub Actions cron is fixed UTC, so each workflow arms crons for both CDT and CST UTC offsets and gates on the current Central hour at job start. The wrong-season cron fires but exits cleanly. Manual `workflow_dispatch` bypasses the gate.

## Year-Round Schedule

| Central Time | Job | Workflow file |
|---|---|---|
| **2:30am** | SambaSafety merge (CSVs → `SambaSafety_Master.xlsx`) | `sambasafety_refresh.yml` |
| **4:00am** | Alvys + Samsara + QB pulls (concurrent) | `refresh.yml`, `samsara_refresh.yml`, `qb_refresh.yml` |
| **4:30am** | Google Sheets KPI dashboard (morning) | `sheets_refresh.yml` |
| **5:00am** | Scorecard email primary (13-page PDF) | `scorecard_email.yml` |
| 5:15 / 5:30 / 6:00am | Scorecard email backups (only fire if primary dropped) | `scorecard_email.yml` |
| **7:15am** | Karpathy-Wiki librarian (morning) | `karpathy_compile.yml` |
| **11:00am** | Alvys + Samsara + QB pulls (midday) | same as 4am |
| **1:00pm** | Google Sheets KPI dashboard (midday) | `sheets_refresh.yml` |
| **1:00pm** | Karpathy-Wiki librarian (afternoon) | `karpathy_compile.yml` |
| **5:00pm** | Alvys + Samsara + QB pulls (evening) | same as 4am |
| **5:30pm** | Google Sheets KPI dashboard (evening) | `sheets_refresh.yml` |

## Why This Ordering

```
2:30am   SambaSafety merge    ──► SambaSafety_Master.xlsx in OneDrive
                                     │ (1.5h buffer)
                                     ▼
4:00am   Alvys + Samsara + QB ──► 3 master workbooks in OneDrive
                                     │ (30 min buffer)
                                     ▼
4:30am   Sheets KPI dashboard ──► Google Sheets refreshed
                                     │ (30 min buffer)
                                     ▼
5:00am   Scorecard email      ──► 13-page PDF in inboxes
                                     │ (2h 15min)
                                     ▼
7:15am   Karpathy librarian   ──► wiki compiled from /raw
```

- **SambaSafety runs first** because the scorecard's page 2 (driver compliance) and page 10 (CSA Scorecard) read its workbook.
- **Three pulls are concurrent** — each writes its own OneDrive folder, no contention.
- **Sheets dashboard is independent** — pulls directly from source APIs, not from OneDrive.

## DST Pattern — How Central Wall-Clock Is Maintained

GitHub Actions cron is fixed UTC and ignores DST. XFreight's solution:

1. **Two cron entries per workflow** — one for CDT (UTC-5) and one for CST (UTC-6).
2. **Gate step at job start** — reads `TZ=America/Chicago date +%-H`, exits cleanly if current Central hour ≠ target.
3. **Manual triggers bypass the gate** — `workflow_dispatch` / `workflow_call` / `push` always run.

Example for 4am target:
```yaml
on:
  schedule:
    - cron: '0 9 * * *'   # 4am CDT (UTC-5)
    - cron: '0 10 * * *'  # 4am CST (UTC-6)
  workflow_dispatch:
```
Gate step: `if TZ=America/Chicago date +%-H | grep -qE '^(4|11|17)$'; then continue; else exit 0; fi`

The wrong-season cron fires but the gate exits it cleanly. **DST flip in early-Nov / mid-Mar requires zero code changes.**

## Per-Workflow Gate Sets

| Workflow | Target CT times | Gate accepts |
|---|---|---|
| `refresh.yml` (Alvys) | 4am / 11am / 5pm | `{4, 11, 17}` |
| `samsara_refresh.yml` | 4am / 11am / 5pm | `{4, 11, 17}` |
| `qb_refresh.yml` | 4am / 11am / 5pm | `{4, 11, 17}` |
| `sambasafety_refresh.yml` | 2:30am | `{2}` |
| `sheets_refresh.yml` | 4:30am / 1pm / 5:30pm | `{4, 13, 17}` |
| `scorecard_email.yml` | 5am + backups through ~6am | `≥ 5` |
| `karpathy_compile.yml` | 7:15am / 1pm | `{7, 13}` |

## Failure Handling

- **Scorecard backups (5:15 / 5:30 / 6:00am):** GitHub Actions cron is best-effort — silent drops during platform load. The scorecard checks a "sent today" marker in OneDrive at startup; only the first cron that fires actually emails.
- **Pull failures:** No built-in retries. A dropped 4am pull means stale data until 11am. The scorecard reads the most recent OneDrive file regardless.
- **QB token rotation:** Happens every run. If `GH_PAT` is missing, warning is logged but old token lasts ~100 days.
- **Scorecard failure notice:** `if: failure()` step sends a failure email to jeff@xfreight.net + jb@xfreight.net.

## Human Operational Rhythm (Reconstructed)

| Time (CT) | Activity |
|---|---|
| 2:30am | SambaSafety merge (auto) |
| 4:00am | Alvys + Samsara + QB pulls (auto) |
| 4:30am | Sheets refresh (auto) |
| 5:00am | Scorecard email (auto) |
| ~6–8am | Jeff + JB read brief, address escalations |
| Morning | Audra: MVR approvals, applicant processing. Dan: load planning, equipment list. Jeff: customer/sales. JB: strategic/financial. |
| Throughout day | Available Equipment List updated as loads move |
| Monday AM | X-Trux weekly fuel reports emailed (~$7K/week average) |
| 11:00am | Midday pulls (auto) |
| 1:00pm | Sheets + librarian (auto) |
| 5:00pm | Evening pulls + Sheets (auto) |
| Overnight | Drivers run loads; safety events flow to Samsara |

## Connections

- [[Data Pipeline Architecture]] — what each job pulls and writes.
- [[Daily Scorecard Email]] — the 5am job described in detail.
- [[OneDrive]] — where all job outputs land.

## Sources

- `raw/xfreight-daily-schedule.md`
- `raw/xfreight-daily-operations-reports.md` (human rhythm)
