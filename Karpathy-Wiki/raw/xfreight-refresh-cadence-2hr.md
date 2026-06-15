# Source-API refresh cadence — every 2 hours, 4am to 6pm CT (seeded 2026-06-14)

> Source: `.github/workflows/refresh.yml`, `samsara_refresh.yml`,
> `qb_refresh.yml` after the June 10 bump from 3x/day to 8x/day.

## What changed

The three source-data pulls used to fire **three times a day** —
4am / 11am / 5pm Central. That cadence worked when the only consumer was
the daily 5am executive brief; by the time the morning brief landed, the
4am Alvys / Samsara / QB pulls were already in place.

The Power BI report and the brief's entity P&L table are intraday
references the office team checks throughout the day, not once. With
a 6-hour gap between pulls, mid-day load activity (new bookings,
status changes, carrier rate adjustments on X-Linx brokered loads)
wasn't visible until the next refresh. We saw this directly when
Power BI's X-Linx June MTD cost showed \$21,890 (stale) while the
API said \$22,282 (current) — \$390 of brokered carrier rate updates
had landed between PBI's last refresh and the brief.

The fix: bump all three refreshes to **every 2 hours from 4am to
6pm CT**. Eight runs per day per source, twenty-four runs total.

## The schedule

Target CT hours: `{4, 6, 8, 10, 12, 14, 16, 18}` — every 2 hours
starting 4am, ending 6pm.

Cron in each workflow:

```yaml
schedule:
  - cron: '0 0,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23 * * *'
```

That single line arms 16 UTC hours covering both DST seasons (CDT =
UTC-5, CST = UTC-6). The `Gate to allowed CT hours` step at the top
of each job exits cleanly when the live wall-clock hour in
`America/Chicago` isn't in the target set:

```bash
case "$CT_HOUR" in
  4|6|8|10|12|14|16|18) echo "Target slot — proceeding." ;;
  *) echo "Off-target — skipping."; echo "skip=1" >> "$GITHUB_OUTPUT" ;;
esac
```

Year-round Central-wall-clock pattern. No DST edits required.

## Why 4am→6pm and not 5am→7pm

The original ask was 5am→7pm (the 8 slots starting at 5am). The
landed schedule shifted to 4am→6pm so the 4am Alvys pull would
still complete before the 5am scheduled brief reads
`Alvys Pipeline.xlsx` from OneDrive. The 7pm slot was dropped
because nothing operational happens after 6pm CT and the cost
of running another full pull purely for an after-hours read was
not justified.

## Cost implications

Each refresh run takes ~5-10 minutes of CI:

- **Alvys** (`refresh.yml`): ~6 min for the full load/trip/fuel/lookups
  pull plus the OneDrive upload of `Alvys Pipeline.xlsx`.
- **Samsara** (`samsara_refresh.yml`): ~3-5 min for the 20-sheet pull
  (loads, trips, fuel, HOS, safety events, vehicle stats, etc.).
- **QB** (`qb_refresh.yml`): ~3-5 min for the five-entity refresh.

Total per day: ~24 runs × ~5 min = ~2 hours of CI time, all within
the free GitHub Actions tier for public/private XFreight usage.

## Idempotency notes

Each pull writes a fresh complete file to OneDrive — they're not
incremental. Running them more frequently doesn't drift the data;
each run reads the same Alvys API and produces the same shape file,
just with newer values. Power BI and the brief always read whatever
the latest file on OneDrive is.

The QuickBooks refresh-token rotation runs on every pull. Tokens
rotate every ~100 days when used, so the increased frequency keeps
them fresh without any new code paths.

## Operational consequences

- The brief's entity P&L (page 1) shows numbers within ~2 hours of
  the latest Alvys booking, vs the prior 6-hour staleness window.
- Power BI desktop users still need to manually refresh PBI to pick
  up the OneDrive file changes — the 2-hour cadence on our side
  doesn't trigger PBI's refresh.
- The `Alvys Master 2026.xlsx` file (the manually-maintained workbook
  PBI reads by default) is **not** updated by these refreshes. That
  file is owned by the standalone Master Fixer app (`src/master_fixer_gui.py`
  + `tools/Alvys Master Fixer.command`). Until the Fixer runs on a
  schedule too, PBI will continue to read whatever the Fixer last
  produced.

## Related

- `xfreight-data-pipeline-architecture.md` — the broader pull/normalize/upload pattern.
- `xfreight-onedrive-and-key-files.md` — file naming conventions.
- `xfreight-power-bi.md` — why PBI reads the Master file, not the Pipeline file.
