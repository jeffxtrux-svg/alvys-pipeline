---
title: Driver Discipline and Incidents
type: concept
tags: [safety, drivers, compliance, fmcsa, dot, incidents]
sources: ["raw/xfreight-driver-discipline-and-incidents.md", "raw/xfreight-safety-program-policies.md"]
related: ["[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Owner-Operator Program]]", "[[Driver Roster]]", "[[Playbook — Driver Disciplinary]]", "[[Coaching Ack]]"]
---

# Driver Discipline and Incidents

## Summary

XFreight uses **written warnings** as the formal disciplinary mechanism for owner-operators and company drivers. Discipline records are maintained in Audra Newman's Sharefile system and are kept separate from the Samsara/Alvys pipeline data — meaning the pipeline currently captures real-time safety events but not historic incident files.

## Documented Incidents

### Brad (BradM / Truck 43195) — March 12, 2026

- **Trigger:** DOT roadside inspection in Wisconsin.
- **Violation:** Chafed brake hoses (likely 49 CFR Part 393 — brake hose/tubing condition).
- **Action:** Written warning issued by Jeff Hannahs; filed in Sharefile by Audra.
- **Impact:** Lands on X-Trux's CSA Maintenance BASIC under DOT #841776. Each roadside accumulation adds risk to the BASIC percentile rank, tracked on brief page 10.

A "chafed brake hose" finding means either a skipped/rushed pre-trip inspection, a hose worn over time and missed in maintenance cycles, or an honest miss on a deteriorating component.

## Discipline Framework

The written warning letter:

1. Names the specific incident (DOT inspection, location, date).
2. Cites the specific regulation violated (e.g., "49 CFR Part 393").
3. States clearly what's expected going forward.
4. Goes into the driver's incident file (Sharefile, maintained by Audra).
5. Subject line uses the driver's first name for quick inbox recognition.

**Typical progression:**

1. First writeup → conversation + documented warning.
2. Second writeup of same type within 60 days → formal written warning + suspension consideration.
3. Third (or any serious violation, crash) → contract termination.

Owner-op contracts can be terminated by X-Trux for cause. See [[Owner-Operator Program]].

## How DOT Inspections Affect XFreight

Each roadside inspection result goes through this path:

1. Result lands in **MCMIS** (Motor Carrier Management Information System) under DOT #841776.
2. Counts toward the applicable **CSA BASIC** (Maintenance for equipment defects, HOS for log violations, Unsafe Driving for moving violations, etc.).
3. Affects X-Trux's BASIC percentile ranks — monitored on brief page 10 (CSA Scorecard).
4. Stays on the record: **24 months** for inspections, **60 months** for crashes.

Page 10 flags intervention when a BASIC crosses 65th percentile (Unsafe Driving, Crash Indicator) or 80th percentile (all others). See [[FMCSA CSA Scorecard]].

## File Structure (Sharefile — not in pipeline)

Per Audra Newman's email (April 23, 2026):

```
Sharefile — Audra — safety
└── new driver truck printouts

Sharefile — incident file — 2014–current
├── By year
└── By driver

Accidents — last 3 yrs by driver
└── (subset of incident file)
```

Records go back to **2014**. The pipeline does **not** currently read these — they're for internal reference, audit response, and DOT inspection support. To surface incident data in the brief, records would need to be replicated to OneDrive or a new Sharefile connector added.

**Coverage gap:** Samsara catches new safety events in real time but knows nothing about historic DOT inspections, Audra's filed writeups, or prior incidents. DOT roadside inspections flow state → FMCSA → MCMIS → SambaSafety CSA Scorecard on a monthly cadence.

## DOT Inspection Workflow

```
1. Driver documents the inspection; notifies dispatch (Jeff or JB) immediately.
2. Audra receives inspection paperwork.
3. Audra files it in Sharefile (by year + by driver).
4. If a violation: Jeff/JB drafts written warning if driver was at fault.
5. Warning emailed to driver; copy filed in Sharefile.
6. FMCSA receives violation data through the state reporting system.
7. Next monthly CSA snapshot reflects the new violation on the BASIC.
```

## Where to Find More Incident Data

Without Sharefile access, useful OneDrive sources:

- `06 - Safety & Compliance/DOT/USDOT_841776_All_BASICs_MotorCarrier_*.xlsx` — periodic CSA snapshots (2024-10-25, 2025-11-28 confirmed).
- `06 - Safety & Compliance/Drivers/{Driver}/` — driver-specific folders may contain incident copies.
- MCMIS PDF: `Documents/Microsoft Teams Chat Files/COMP841776_jb0257_428202610853.pdf` — 2-year inspection + crash history.

## Connections

- [[Safety Program]] — the full safety rubric, Sharefile structure, driver MVR workflow.
- [[Playbook — Driver Disciplinary]] — the protocol for responding to any trigger (Samsara event, DOT incident, customer escalation).
- [[Coaching Ack]] — how the brief derives ack state from Samsara SafetyEvents.
- [[FMCSA CSA Scorecard]] — where DOT inspection violations accumulate into BASIC percentile ranks.
- [[Driver Roster]] — driver identities; Brad = BradM / Truck 43195.
- [[Owner-Operator Program]] — lease termination vs employment termination.

## Sources

- `raw/xfreight-driver-discipline-and-incidents.md`
- `raw/xfreight-safety-program-policies.md`
