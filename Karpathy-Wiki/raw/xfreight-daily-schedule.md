# XFreight daily schedule — workflow timing (seeded 2026-06-05 from repo)

> Source: `CLAUDE.md` automation table, `.github/workflows/*.yml`, plus
> `docs/knowledge-base/automation-and-secrets.md`.

## Year-round Central wall-clock schedule

| Time (CT) | Job | Workflow file |
|---|---|---|
| 2:30am | SambaSafety merge (raw CSVs → SambaSafety_Master.xlsx → OneDrive) | `sambasafety_refresh.yml` |
| 4:00am | Alvys + Samsara + QB pulls (concurrent) | `refresh.yml`, `samsara_refresh.yml`, `qb_refresh.yml` |
| 4:30am | Google Sheets KPI dashboard refresh (morning) | `sheets_refresh.yml` |
| 5:00am | Scorecard email — primary (13-page PDF brief, sent to jeff@xfreight.net + jb@xfreight.net) | `scorecard_email.yml` |
| 5:15am / 5:30am / 6:00am | Scorecard email — defense-in-depth backup slots (only fire if a prior slot was dropped by GitHub Actions) | `scorecard_email.yml` |
| 7:15am | Karpathy-Wiki librarian compile (morning — reads /raw, writes /wiki, commits to main) | `karpathy_compile.yml` |
| 11:00am | Alvys + Samsara + QB pulls (midday) | same as 4am |
| 1:00pm | Google Sheets KPI dashboard refresh (midday) | `sheets_refresh.yml` |
| 1:00pm | Karpathy-Wiki librarian compile (afternoon) | `karpathy_compile.yml` |
| 5:00pm | Alvys + Samsara + QB pulls (evening) | same as 4am |
| 5:30pm | Google Sheets KPI dashboard refresh (evening) | `sheets_refresh.yml` |

## How the year-round Central wall-clock guarantee works

GitHub Actions cron is fixed UTC and ignores DST. To hit the same Central wall-clock time in both CDT (mid-Mar → early Nov) and CST (early Nov → mid-Mar), every workflow uses the **dual-cron + CT-hour-gate** pattern:

1. **Two cron families.** Each workflow arms a cron entry for the CDT UTC slot (e.g. `0 9 UTC` = 4am CDT) AND for the CST UTC slot (e.g. `0 10 UTC` = 4am CST).
2. **A "Gate to allowed CT hours" step** at the top of the job reads `TZ=America/Chicago date +%-H` and exits cleanly if the current Central hour isn't in the target set.
3. **Manual `workflow_dispatch` / `workflow_call` / `push` triggers bypass the gate** so on-demand runs work at any hour.

So the wrong-season cron still fires, but the gate skips it. The DST flip in early-Nov / mid-Mar requires zero code changes.

## Per-workflow target hours (gate sets)

| Workflow | Target Central times | Gate accepts |
|---|---|---|
| `refresh.yml` (Alvys) | 4am / 11am / 5pm | `{4, 11, 17}` |
| `samsara_refresh.yml` | 4am / 11am / 5pm | `{4, 11, 17}` |
| `qb_refresh.yml` | 4am / 11am / 5pm | `{4, 11, 17}` |
| `sambasafety_refresh.yml` | 2:30am | `{2}` |
| `sheets_refresh.yml` | 4:30am / 1pm / 5:30pm | `{4, 13, 17}` |
| `scorecard_email.yml` | 5am (primary) + backups through ~6am | `≥ 5` |
| `karpathy_compile.yml` | 7:15am / 1pm | `{7, 13}` |

## Why this ordering

```
2:30am   SambaSafety merge       ─►  SambaSafety_Master.xlsx in OneDrive
                                          │ (1.5h buffer)
                                          ▼
4:00am   Alvys + Samsara + QB    ─►  3 master workbooks in OneDrive
                                          │ (30 min buffer)
                                          ▼
4:30am   Sheets KPI dashboard    ─►  Google Sheets refreshed for the day
                                          │ (30 min buffer)
                                          ▼
5:00am   Scorecard email         ─►  13-page PDF in inboxes
                                          │ (2h 15min)
                                          ▼
7:15am   Karpathy librarian      ─►  yesterday's brief compiled into wiki
```

- SambaSafety runs FIRST because the scorecard's page 2 (driver compliance) and page 10 (CSA scorecard) read its workbook.
- The three pulls are concurrent — each writes its own OneDrive folder with its own credentials, no contention.
- The Sheets dashboard runs in parallel with the scorecard prep window. Sheets pulls from the source APIs directly (not OneDrive), so it's independent of the OneDrive write timing.

## Failure handling

- **Scorecard backups (5:15 / 5:30 / 6:00am)** exist because GitHub Actions cron is documented as best-effort — it silently drops scheduled runs during platform load. The scorecard script checks a "sent today" marker in OneDrive at startup and exits clean if today's brief already landed, so only the first cron that fires actually emails.
- **Pull failures don't have built-in retries.** A dropped 4am pull means the data is stale until 11am. The scorecard email reads the most recent OneDrive file regardless of which run wrote it, so a stale workbook will still email — the data-check banner on page 1 surfaces freshness.
- **QuickBooks refresh-token rotation** happens on every run. If `GH_PAT` is missing the rotation logs a warning but the old token works for ~100 days.
- **Scorecard failure-notice email** fires from `if: failure()` in `scorecard_email.yml`. Sent to jeff@xfreight.net + jb@xfreight.net so a broken morning is noticed instead of going quiet.
