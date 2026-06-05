# XFreight safety program — rules and rubrics (seeded 2026-06-05 from repo)

> Source: `src/scorecard_email.py` (compute_speed_comment, _safety_detail_tables,
> _CSA_INTERVENTION, all the safety builders), `docs/knowledge-base/connector-samsara.md`,
> `docs/knowledge-base/connector-sambasafety.md`, recent PRs (#86, #90, #91).

## Safety data sources

- **Samsara** (telematics) — real-time safety events, HOS violations, DVIR defects, driver safety scores, speed-over-limit, idle time. Drives pages 3, 4, 8, 9.
- **SambaSafety** (MVR / FMCSA program) — license expirations, driver risk index, violations, CSA carrier scorecard. Drives pages 2 and 10.
- **Alvys** Drivers sheet — DOT medical card expirations (the "DOT physical" date), since SambaSafety doesn't carry that field.

## Speed-over-limit rubric (page 4 + page 1 Bottom Line)

For each driver, the system computes time-over-posted-limit ÷ total drive time (as %) across three windows: 6-month, 3-month, MTD. The **peak** of the three determines the base comment:

| Peak % | Base comment | BL escalation? |
|---|---|---|
| ≥ 3.0% | "STOP this driver now" | **YES** (STOP-THIS-DRIVER tier) |
| ≥ 2.5% | "Need to sit down with this driver — they have a problem" | **YES** (Sit-down tier) |
| ≥ 2.25% | "This is too fast" | No |
| ≥ 2.0% | "Driver needs a conversation" | No |
| ≥ 1.75% | "Where is the fire?" | No |
| ≥ 1.5% | "We have a problem with speed" | No |
| ≥ 1.25% | "Watch this driver" | No |

A **trend phrase** layers on top:

- `MTD - max(6mo, 3mo) ≥ 2.0%` → "spiking — recent jump, address now" (BL: still escalates)
- `6mo ≥ 1.0% AND MTD ≤ 6mo × 0.3` → "falling fast — keep it up" (BL: EXCLUDED)
- `6mo ≥ 1.0% AND MTD ≤ 6mo × 0.6` → "improving — keep it up" (BL: EXCLUDED)
- `MTD - 6mo ≥ 1.0%` → "trending worse" (BL: still escalates)
- Otherwise if base set + `MTD ≥ 6mo - 0.1%` → "no improvement — requires action" (BL: still escalates)

## Why the BL excludes improvers

Drivers who are actively fixing their speeding shouldn't be named in the morning escalation list. The page-4 detail table still shows them with the "STOP" / "Sit-down" label so management has full visibility, but the Bottom Line on page 1 only names drivers whose trend doesn't show "improving" or "falling fast".

**The same comment generator (`compute_speed_comment` in `src/scorecard_email.py`) drives both the page-4 detail and the BL exclusion**, so the two physically cannot disagree even if the rubric is tuned later.

## Coaching needs assigned (page 1, page 3 detail)

Per-driver list aggregating safety events over the last 30 days:

- **Monitor** (events < `COACH_EVENT_THRESHOLD = 2`) — single events. Rolls off the list naturally after 7 days from the last event. Ack column reads "n/a" because single events don't need driver acknowledgment.
- **Assign coaching** (events ≥ 2) — driver stays on the list until they sign their Samsara coaching session, then for 3 more days (`_ACK_KEEP_DAYS = 3`) as a closeout indicator. Ack column shows ✓ (green) when signed.

The driver signing is detected from the Samsara CoachingSessions sheet — `Status == completed` with `Completed At` timestamp at or after the event.

## CSA Carrier Scorecard (page 10, FMCSA)

The SambaSafety **CSA2010 Preview Scorecard CSV** lands in OneDrive and is merged into `SambaSafety_Master.xlsx` as a third sheet (`CSA Scorecard`).

For X-Trux (DOT #841776), the page renders BASIC percentile ranks. Each category gets an INTERVENTION LIKELY flag at FMCSA's documented thresholds:

| BASIC category | Percentile alert threshold |
|---|---|
| Unsafe Driving | **65** |
| Crash Indicator | **65** |
| Maintenance | 80 |
| HOS Compliance | 80 |
| Hazardous Materials | 80 |
| Driver Fitness | 80 |
| Controlled Substances / Alcohol | 80 |

Unsafe Driving and Crash Indicator alert sooner because they correlate most directly with public-safety risk. The intervention table lives in `_CSA_INTERVENTION` in `src/scorecard_email.py`.

WATCH status fires at 75% of the intervention threshold; OK below that.

**Fails soft.** If `CSA2010 Preview Scorecard.csv` is absent from `OneDrive/SambaSafety/`, the page renders a "data unavailable" callout instead of crashing.

## MVR & license program (page 2)

Two SambaSafety reports plus the Alvys Drivers feed drive page 2:

- **Risk Index Report** → per-driver: license #, status, expiration, state, risk score, score bucket (Clean / Activity / Exception → Low / Medium / High).
- **MVR Violations Report** → per-violation: date, type, points/score, severity. **90-day window** for the brief's tile + table (down from 365d in PR #90, to focus on recent risk).
- **Alvys Drivers sheet** → DOT medical card expirations. 30-day pipeline + 14-day critical window.

License expiring tile uses `LICENSE_EXPIRY_WARN_DAYS = 60`. High-risk threshold `SAMBA_HIGH_RISK_SCORE = 16` when no category column is present.

Action items / bottom-line callouts that can fire:

- `CDL EXPIRED · DRIVER NAME` (severity bad) — license past expiration or expires within 7 days.
- `CDL RENEWALS UPCOMING` (severity warn) — 30-day horizon.
- `MVR HIGH RISK · N DRIVERS` (severity warn) — drivers in the High risk bucket.
- `DOT MEDICAL CARD · NAME` (bad) — 7-day critical window on DOT physical expiration.

## Equipment compliance (pages 5 & 6)

- **Page 5: Tractor inspections.** Annual DOT inspection (365-day federal rule), 120-day company policy on top of the last inspection date.
- **Page 6: Trailer inspections.** Same federal + company policy.

Fed by `compute_equipment` over the Alvys Trucks + Trailers sheets with `Maintenance` DOT-inspection dates overlaid onto each unit.

Trailers overdue on the 120-day company policy get a bottom-line callout naming the units (up to 8 + "and N more").
