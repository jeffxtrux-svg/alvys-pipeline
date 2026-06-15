---
title: Refresh Cadence
type: concept
tags: [automation, schedule, github-actions, pipeline, data-freshness]
sources: ["raw/xfreight-refresh-cadence-2hr.md", "raw/xfreight-daily-schedule.md"]
related: ["[[Daily Schedule]]", "[[Data Pipeline Architecture]]", "[[OneDrive]]", "[[Power BI]]", "[[Daily Scorecard Email]]"]
---

# Refresh Cadence

## Summary

As of June 2026, the three source-data pulls (Alvys, Samsara, QuickBooks) run **every 2 hours from 4am to 6pm Central** — eight runs per day per source, twenty-four total. This replaced the prior 3x/day schedule (4am / 11am / 5pm) after mid-day data staleness was confirmed to matter for the Power BI report and the entity P&L table.

## What Changed and Why

The prior 3x/day cadence left a **6-hour gap** between pulls. The office team checks Power BI and the brief's entity P&L table throughout the day, not once. Mid-day load activity (new bookings, carrier-rate updates on X-Linx brokered loads) wasn't visible until the next refresh.

The trigger: Power BI's X-Linx June MTD cost showed $21,890 (stale) while the API showed $22,282 (current) — $390 of brokered carrier rate updates had landed between PBI's last refresh and the brief.

The fix: bump all three refreshes to every 2 hours from 4am to 6pm CT.

## The Schedule

**Target CT hours:** `{4, 6, 8, 10, 12, 14, 16, 18}` — every 2 hours starting 4am, ending 6pm.

**Cron (in each workflow):**

```yaml
schedule:
  - cron: '0 0,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23 * * *'
```

That single line arms 16 UTC hours covering both DST seasons (CDT = UTC-5, CST = UTC-6). The `Gate to allowed CT hours` step at job start exits cleanly when the live Central hour is not in the target set.

**Why 4am→6pm and not 5am→7pm:** The 4am pull ensures the brief can read fresh data at 5am. The 7pm slot was dropped — no operational activity happens after 6pm CT, and the cost of a full pull purely for an after-hours read was not justified.

## Cost

~24 runs/day × ~5 min each ≈ 2 hours of CI per day. Within the free GitHub Actions tier.

| Source | Typical duration |
|---|---|
| Alvys (`refresh.yml`) | ~6 min (full load/trip/fuel/lookups pull + OneDrive upload) |
| Samsara (`samsara_refresh.yml`) | ~3–5 min (20-sheet pull) |
| QuickBooks (`qb_refresh.yml`) | ~3–5 min (five-entity refresh) |

## Idempotency

Each pull fully rewrites its OneDrive file — not incremental. Running more frequently doesn't drift the data; each run reads the same source API and produces the same schema, just with newer values. Power BI and the brief always read whatever the latest OneDrive file is.

The QuickBooks refresh-token rotation runs on every pull. Increased frequency keeps tokens fresh without new code paths.

## Operational Consequences

- The brief's entity P&L (page 1) shows numbers within ~2 hours of the latest Alvys booking, vs the prior ~6-hour staleness window.
- **Power BI desktop users still must manually refresh PBI** to pick up OneDrive file changes — the 2-hour cadence on XFreight's side does not trigger PBI's own refresh.
- **`Alvys Master 2026.xlsx`** (the hand-maintained workbook PBI reads by default) is **not** updated by these refreshes. That file is owned by the standalone Master Fixer app. Until the Fixer runs on a schedule, PBI will continue reading whatever the Fixer last produced.

## Connections

- [[Daily Schedule]] — the full automation schedule; this cadence update changes the `refresh.yml`, `samsara_refresh.yml`, `qb_refresh.yml` gate sets.
- [[Data Pipeline Architecture]] — the pull/transform/write/upload skeleton.
- [[Power BI]] — why PBI reads the Master file, not the Pipeline file.
- [[OneDrive]] — file naming conventions; critical distinction between `Alvys Pipeline.xlsx` and `Alvys Master 2026.xlsx`.

## Sources

- `raw/xfreight-refresh-cadence-2hr.md`
