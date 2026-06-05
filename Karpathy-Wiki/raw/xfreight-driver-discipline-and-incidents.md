# XFreight driver discipline + DOT incidents (seeded 2026-06-05 from Outlook)

> Source: Jeff Hannahs email "Brad" (March 12, 2026), Audra's incident filing
> system references.

## Discipline framework (inferred from observed patterns)

XFreight uses **written warnings** as the formal disciplinary mechanism for owner-operators / drivers. The warning letter:

1. Names the specific incident (DOT inspection, location, date)
2. Cites the **specific regulation violated** (e.g. "49 CFR..." Part references)
3. Includes a clear statement of what's expected going forward
4. Goes into the driver's incident file (Audra's Sharefile system, see `xfreight-safety-program.md`)
5. Subject line uses the driver's first name (so it's quickly recognizable in inbox)

This is the standard owner-op-fleet practice: warnings → suspension consideration → termination of contract (per the Owner-Op contract; see `xfreight-owner-operator-program.md`).

## Documented incidents

### Brad — March 12, 2026
- **Subject:** "Brad" (Jeff's email)
- **Cause:** DOT roadside inspection in Wisconsin
- **Citation:** Chafed brake hoses (likely 49 CFR Part 393)
- **Letter type:** Written Warning
- **Driver:** "Brad" — maps to `BradM` in the driver roster (truck 43195)

A "chafed brake hose" violation is a maintenance/inspection failure — typically the driver's pre-trip should have caught it before the DOT inspector did. It indicates either:
- Skipped or rushed pre-trip inspection
- Hose worn over time and missed in maintenance cycles
- Honest miss on a deteriorating component

Either way, it goes on X-Trux's CSA Maintenance BASIC and threatens the BASIC percentile if it accumulates.

## How DOT inspections affect XFreight

Each roadside inspection result is reported to FMCSA and:

1. Lands in **MCMIS** (Motor Carrier Management Information System) under DOT #841776
2. Counts toward the **CSA Maintenance BASIC** (or HOS, Unsafe Driving, etc. depending on violation type)
3. Affects X-Trux's BASIC percentile ranks — the page-10 CSA Scorecard report on the brief
4. Stays on the record for 24 months for inspections, 60 months for crashes

The page-10 brief flags any BASIC at:
- **65th percentile** for Unsafe Driving / Crash Indicator
- **80th percentile** for all other BASICs (including Maintenance)

So a Brad-type chafed-hose violation hits Maintenance — currently below intervention threshold but each accumulation adds risk.

## Where incident records live

Per Audra's "Information requested" email (Apr 23, 2026):

```
Sharefile - Audra - safety
├── new driver truck printouts
│
Sharefile - incident file - 2014-current
├── By year
└── By driver
│
Accidents - last 3 yrs by driver  (subset of incident file)
```

The pipeline **does not currently parse** these — they're in Sharefile, not in the OneDrive folders the pipeline reads. To surface incident data in the brief, either:

- The records would need to be replicated to OneDrive
- A new Sharefile connector would need to be added to the pipeline

This is **a gap in the daily brief's safety visibility** — Samsara catches new safety events but doesn't know about historic DOT inspections / writeups / Audra's filed incidents.

## DOT inspection workflow

When a driver gets pulled over for a DOT inspection:

1. **Driver** documents the inspection on their copy of the inspection report
2. **Driver** notifies dispatch (Jeff or JB) immediately
3. **Audra** receives the inspection paperwork
4. Audra files it in Sharefile (by year + by driver)
5. If a violation is cited, Jeff/JB drafts a written warning if the driver was at fault
6. Warning goes to driver via email; copy filed in Sharefile
7. FMCSA receives the violation data through the state's reporting system
8. Next monthly CSA snapshot reflects the new violation on the BASIC

## How to find more incident data

Without Sharefile access, key sources in OneDrive:

- `06 - Safety & Compliance/DOT/USDOT_841776_All_BASICs_MotorCarrier_*.xlsx` — periodic CSA snapshots (2024-10-25, 2025-11-28 snapshots present)
- `06 - Safety & Compliance/Drivers/{Driver}/` — driver-specific folders may contain incident copies
- MCMIS PDF: `Documents/Microsoft Teams Chat Files/COMP841776_jb0257_428202610853.pdf` — 2-year inspection + crash history

Recent (last 24h) safety events come into the brief via Samsara, which catches:
- Hard braking, harsh acceleration, harsh turning
- Speed-over-limit
- Following distance violations
- Lane departure

But **DOT roadside inspections are not in Samsara** — those go through the state → FMCSA → MCMIS → SambaSafety CSA Scorecard pathway, which is monthly cadence.

## Driver retention implications

Writeups are tracked in `XFreight Goals.xlsx` driver roster + the incident file. A driver with multiple writeups in a short window typically gets:

1. First writeup → conversation + documented warning
2. Second writeup → final warning + suspension consideration
3. Third (or any serious violation like accident) → contract termination

Owner-op contracts can be terminated by X-Trux for cause (per `xfreight-owner-operator-program.md`). The 5-year-old-truck-max requirement and 4-quarterly-inspection coverage are XFreight's investment in keeping drivers compliant.
