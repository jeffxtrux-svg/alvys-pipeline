---
title: Safety Program
type: concept
tags: [safety, compliance, samsara, sambasafety, fmcsa]
sources: ["raw/xfreight-safety-program.md", "raw/xfreight-safety-program-policies.md", "raw/xfreight-driver-discipline-and-incidents.md"]
related: ["[[FMCSA CSA Scorecard]]", "[[DOT Inspection Policy]]", "[[Driver Roster]]", "[[Key People]]", "[[Daily Scorecard Email]]", "[[Owner-Operator Program]]", "[[Coaching Ack]]", "[[Progressive Discipline Policy]]"]
---

# Safety Program

XFreight's safety compliance program spans driver screening (pre-hire MVR/PSP), daily Samsara monitoring (telematics), SambaSafety MVR tracking, and FMCSA CSA scorecard oversight. Safety data drives pages 2–6 and 10 of the [[Daily Scorecard Email]].

## Summary

Every prospective driver runs through an Acrisure/Great West MVR+PSP approval before hire. Active drivers are monitored in Samsara (safety events, speed-over-limit, HOS, DVIR) and SambaSafety (license status, risk index). The daily brief surfaces speed escalations in the Bottom Line and tables violations on pages 3–4. DOT inspections flow through FMCSA → MCMIS → SambaSafety CSA Scorecard (monthly cadence).

## Key Ideas

- **No driver-facing cameras** — a deliberate recruiting differentiator (forward-facing only).
- **120-day company DOT inspection policy** on top of the federal 365-day annual requirement.
- Driver hiring requires **both** Audra's approval AND Acrisure/Great West underwriting sign-off.
- Safety manual is maintained by Audra Newman and last revised Jan 1, 2022.
- DOT incidents (roadside inspections, crashes) are NOT in Samsara — they flow through FMCSA/MCMIS → SambaSafety CSA (monthly).

## Data Sources by Brief Page

| Page | Source | Content |
|---|---|---|
| Page 2 | SambaSafety Risk Index + MVR Violations + Alvys Drivers | License status, expirations, risk scores, DOT medical cards |
| Page 3 | Samsara | Last 24h safety events, HOS violations, DVIR defects, coaching needs |
| Page 4 | Samsara | Per-driver speed-over-limit % with 6mo/3mo/MTD windows + comments |
| Pages 5–6 | Alvys Trucks + Trailers | Tractor + trailer inspection compliance (120d + 365d) |
| Page 10 | SambaSafety CSA CSV | FMCSA BASIC percentile ranks (see [[FMCSA CSA Scorecard]]) |

## Speed-Over-Limit Rubric (Page 4)

For each driver, peak of (6-month, 3-month, MTD) % time over posted limit determines the base comment:

| Peak % | Comment | Bottom-Line escalation? |
|---|---|---|
| ≥ 3.0% | "STOP this driver now" | YES (STOP-THIS-DRIVER tier) |
| ≥ 2.5% | "Need to sit down with this driver — they have a problem" | YES (Sit-down tier) |
| ≥ 2.25% | "This is too fast" | No |
| ≥ 2.0% | "Driver needs a conversation" | No |
| ≥ 1.75% | "Where is the fire?" | No |
| ≥ 1.5% | "We have a problem with speed" | No |
| ≥ 1.25% | "Watch this driver" | No |

**Trend phrases** layer on top:
- "spiking — recent jump, address now" (when MTD - max(6mo,3mo) ≥ 2.0%)
- "falling fast — keep it up" (improving significantly; **excluded from Bottom Line**)
- "improving — keep it up" (modest improvement; **excluded from Bottom Line**)
- "trending worse" (worsening)
- "no improvement — requires action"

**Why excludes improvers:** Drivers actively fixing their speeding shouldn't be named in the morning escalation, but they still appear on page 4 so management has full visibility. The same `compute_speed_comment` generator drives both page-4 and Bottom Line — they cannot disagree.

## Coaching Needs Assigned (Page 1 + Page 3)

Two-tier policy on the Coaching needs assigned list:

| Tier | Events | Behavior |
|---|---|---|
| **Monitor** | < `COACH_EVENT_THRESHOLD` (2) | Drops off 7 days after last event. Ack = "n/a". |
| **Assign coaching** | ≥ 2 | Stays until all events for that driver are coached, then 3 more days (`_ACK_KEEP_DAYS = 3`). Shows **Coach** and **Ack** columns. |

**Ack derivation (as of 2026-06-06 fix):** Ack state is derived from each safety event's `coachingStatus` field on the SafetyEvents sheet — `all_coached = True` when every event in the 30-day window has status in `{coached, dismissed, recognized}`. The `coach` field is the most-frequent `coachedBy.name` across coached events. `ack_ts` is the latest `coachedAtTime` (falling back to the event timestamp if unpopulated).

> **Note:** The original design (PR #86) derived acks from Samsara's CoachingSessions sheet using a `coaching_acks` dict and `_ack_after()` helper. That approach was broken from the start — Samsara's `/coaching/sessions` endpoint returns HTTP 404 on every run, so the CoachingSessions sheet was always a placeholder and the Ack column always showed em-dash. The June 6 fix replaced that entirely. See [[Coaching Ack]] for the full root-cause analysis.

## MVR & License Program (Page 2)

- **MVR violation window:** 90 days (`VIOLATION_WINDOW_DAYS = 90`; changed from 365 in PR #88).
- **License expiring soon:** 60-day warn window (`LICENSE_EXPIRY_WARN_DAYS = 60`).
- **High-risk score threshold:** 16 (`SAMBA_HIGH_RISK_SCORE = 16` when no category column).
- **DOT medical card warn:** 30 days (`MEDICAL_EXPIRY_WARN_DAYS`); critical: 14 days.

Bottom-Line callouts that can fire: `CDL EXPIRED`, `CDL RENEWALS UPCOMING`, `MVR HIGH RISK · N DRIVERS`, `DOT MEDICAL CARD · DRIVER`.

## Equipment Compliance (Pages 5 & 6)

Two compliance windows — see [[DOT Inspection Policy]] for the canonical language rules and rationale:
1. **Federal annual inspection:** 365 days (out-of-service threshold if crossed).
2. **XFreight company policy:** 120 days from last inspection (operational deadline; unit still in service).

The 120-day company policy is the binding constraint — it fires sooner than the federal rule. Trailers overdue on the 120-day policy get a Bottom-Line callout naming up to 8 units + "and N more."

Inspection dates come from Alvys Trucks / Trailers sheets with the `Maintenance` DOT-inspection date overlaid.

## Driver Applicant Approval Workflow

```
1. Applicant → fills out X-Trux application
2. Audra → runs MVR + PSP Report (FMCSA Pre-Employment Screening)
3. Audra → emails application + MVR + PSP to Jami Hewitt (jhewitt@acrisure.com)
4. Jami → runs against Great West Casualty underwriting guidelines
5a. Approved → "meets Great West guidelines; let me know if hired"
5b. Declined → flags specific issues (e.g. expired CDL in wrong state)
6. If approved + hired: Audra creates folder in Sharefile + OneDrive
7. Driver onboarded; truck assigned; appears in Alvys
```

## Discipline Framework

XFreight codified a formal **5-level progressive discipline policy** on June 16, 2026. See [[Progressive Discipline Policy]] for the full structure — two parallel tracks (OO contract vs. Truk-Way employee), entry-point rules for severe incidents, immediate-termination grounds, and the Samsara speed-flag → level mapping.

Key integration points between the safety brief and the policy:
- **Page 4 speed flags** map directly to Level 1–2 discipline entry points; Bottom Line escalation two consecutive weeks = automatic Level 2.
- **Page 3 coaching backlog** — unacknowledged coaching after 14 days = Level 1 trigger.
- **Page 10 CSA BASIC** — percentiles approaching thresholds (65th/80th) accelerate the escalation path.

Documentation standard: every letter names the specific incident, cites the 49 CFR Part, states expected change, requires driver signature. Jeff Hannahs drafts; Audra Newman files in Sharefile.

### Known Active Case

- **BradM (truck 43195)** — March 12, 2026 DOT inspection in Wisconsin; chafed brake hoses (49 CFR Part 393). Written warning by Jeff. Under the formal policy this is a **Level 2** action. Any subsequent violation triggers Level 3 review before next load assignment.

## Incident Records Location

Per Audra's "Information requested" email (Apr 23, 2026):
- **Sharefile – Audra – safety** → new driver truck printouts.
- **Sharefile – incident file – 2014-current** → by year + by driver.
- **Accidents – last 3 years by driver** → subset.

The pipeline does NOT parse these (Sharefile, not OneDrive). A gap in daily brief safety visibility for historic DOT inspection data.

## How DOT Inspections Flow Into the Brief (Indirectly)

DOT roadside inspections are NOT in Samsara. They flow: state reporting → FMCSA MCMIS → SambaSafety CSA Scorecard (monthly CSV). The page-10 CSA Scorecard is the only brief page that reflects roadside inspection history.

## Connections

- [[FMCSA CSA Scorecard]] — BASIC percentile ranks driven by roadside inspections.
- [[Driver Roster]] — drivers by name, truck assignment, mileage.
- [[Key People]] — Audra Newman manages the program; Jami Hewitt (Acrisure) approves applicants.
- [[Daily Scorecard Email]] — pages 2–6 + 10.
- [[Owner-Operator Program]] — Samsara ELD + camera provided; no driver-facing camera.

## Sources

- `raw/xfreight-safety-program.md` — code-level rubrics + constants.
- `raw/xfreight-safety-program-policies.md` — business policies, applicant workflow, discipline.
- `raw/xfreight-driver-discipline-and-incidents.md` — incident records location, DOT flow.
- `raw/xfreight-progressive-discipline-policy.md` — formal 5-level discipline policy (June 16, 2026).
