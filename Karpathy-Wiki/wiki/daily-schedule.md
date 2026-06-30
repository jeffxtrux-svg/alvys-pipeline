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
| **1am / 3am** | SambaSafety merge (CSVs → `SambaSafety_Master.xlsx`) | `sambasafety_refresh.yml` |
| **4:00am** | Alvys + Samsara + QB pulls (1st of 8 daily runs) | `refresh.yml`, `samsara_refresh.yml`, `qb_refresh.yml` |
| **4:30am** | Google Sheets KPI dashboard (morning) | `sheets_refresh.yml` |
| **5:00am** | Safety & Compliance report primary | `safety_compliance_email.yml` |
| **5:00am** | Scorecard email primary (13-page PDF) | `scorecard_email.yml` |
| 5:15 / 5:30am | Scorecard email backups (only fire if primary dropped) | `scorecard_email.yml` |
| **5:30am** | Cloudflare Worker dispatches all three healthchecks | External — `ops/cron-trigger/worker.js` |
| **6:00am** | Scorecard / Daily-upload / Safety healthchecks (marker-gated) | `scorecard_healthcheck.yml`, `daily_upload_healthcheck.yml`, `safety_compliance_healthcheck.yml` |
| **6:00am / 8:00am** | Alvys + Samsara + QB pulls (2nd / 3rd runs) | same as 4am |
| **7:00am** | Financial Brief (AR + invoicing focus) | `financial_email.yml` |
| **7:15am** | Karpathy-Wiki librarian (morning) | `karpathy_compile.yml` |
| **10:00am / 12:00pm / 2:00pm** | Alvys + Samsara + QB pulls (4th–6th runs) | same as 4am |
| **1:00pm** | Google Sheets KPI dashboard (midday) | `sheets_refresh.yml` |
| **1:00pm** | Karpathy-Wiki librarian (afternoon) | `karpathy_compile.yml` |
| **4:00pm / 6:00pm** | Alvys + Samsara + QB pulls (7th–8th runs) | same as 4am |
| **5:30pm** | Google Sheets KPI dashboard (evening) | `sheets_refresh.yml` |
| **Every :15 / :45** | ETA tracker backstop (Cloudflare Worker) | External — `ops/cron-trigger/worker.js` |

### Source Data Refresh Cadence (as of June 10, 2026)

Alvys, Samsara, and QuickBooks pulls were bumped from 3×/day (4am / 11am / 5pm) to **8×/day** (every 2 hours from 4am to 6pm CT). Target hours: `{4, 6, 8, 10, 12, 14, 16, 18}`.

**Why:** The Power BI report and brief entity P&L are checked intraday, not just at 5am. With a 6-hour gap between pulls, mid-day load activity (new bookings, status changes, brokered carrier rate adjustments) wasn't visible until the next refresh. The specific trigger: Power BI's X-Linx June MTD cost showed $21,890 (stale) while the API said $22,282 (current) — $390 of carrier rate updates had landed between PBI's last pull and the brief.

**Cost:** ~24 CI-minutes/day across the 3 source workflows × 8 runs × 3 sources — well within GitHub Actions' free tier.

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
| `refresh.yml` (Alvys) | every 2h, 4am–6pm | `{4, 6, 8, 10, 12, 14, 16, 18}` |
| `samsara_refresh.yml` | every 2h, 4am–6pm | `{4, 6, 8, 10, 12, 14, 16, 18}` |
| `qb_refresh.yml` | every 2h, 4am–6pm | `{4, 6, 8, 10, 12, 14, 16, 18}` |
| `sambasafety_refresh.yml` | 1am + 3am + every 2h 4am–6pm | `{1, 2, 3, 4, 6, 8, 10, 12, 14, 16, 18}` |
| `sheets_refresh.yml` | 4:30am / 1pm / 5:30pm | `{4, 13, 17}` |
| `safety_compliance_email.yml` | 5am + backups | `≥ 5, skip 6` |
| `scorecard_email.yml` | 5am + backups through ~7am | `≥ 5, skip 6` |
| `scorecard_healthcheck.yml` | 6am | `{6}` |
| `daily_upload_healthcheck.yml` | 6am | `{6}` |
| `safety_compliance_healthcheck.yml` | 6am | `{6}` |
| `financial_email.yml` | 7am | `≥ 7, skip 8` |
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
- [[Daily Scorecard Email]] — the 5am scorecard job described in detail.
- [[Slack & Teams Digest]] — fires immediately after scorecard email completes.
- [[OneDrive]] — where all job outputs land.

## Sources

- `raw/xfreight-daily-schedule.md`
- `raw/xfreight-daily-operations-reports.md` (human rhythm)
- `raw/xfreight-refresh-cadence-2hr.md` — source-data pull bump to 8×/day (June 10, 2026)
