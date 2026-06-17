# XFreight Accountability Category Playbooks — Source Material (seeded 2026-06-17)

> Source: XFreight safety brief system (Teams Adaptive Cards + scorecard email), `src/scorecard_email.py`,
> `Karpathy-Wiki/raw/xfreight-progressive-discipline-policy.md`,
> `Karpathy-Wiki/raw/xfreight-safety-program.md`,
> `Karpathy-Wiki/raw/xfreight-safety-program-policies.md`,
> `Karpathy-Wiki/raw/xfreight-dot-inspection-policy.md`.
> Compiled: 2026-06-17.

---

## Overview — The Accountability System

XFreight's daily safety brief (email + Teams Adaptive Cards) surfaces per-driver and per-unit items across 9 accountability categories. When Audra or ops sees an item in the Teams morning post or brief email, this source material is the authoritative guide for what it means, what the FMCSA consequence is, and exactly what action to take.

The accountability system runs a 30-day rolling window per driver. Occurrences within that window drive the escalation tier shown in the Teams card badge:

| Occurrence in 30d | Badge signal in Teams card | Required action | Who acts |
|---|---|---|---|
| 1st | No badge (or "1st") | Coach | Audra |
| 2nd | ⚠️ "2nd in 30d" | Verbal warning | Audra |
| 3rd | 🔴 "3rd in 30d" | Written warning | Audra |
| 4th+ | 🚨 "#N in 30d" | Escalate to JB immediately | Audra → JB |

**Mapping to formal discipline levels:**
- Coach (1st) = Formal Level 1 — Verbal Counseling
- Verbal warning (2nd) = Formal Level 2 — Written Warning
- Written warning (3rd) = Formal Level 3 — Strong Written Notice
- Escalate (4th+) = Formal Level 4 review; management determines next step

**Equipment / DVIR items** use a softer ladder: schedule/repair → escalate if no action in defined window. No warning ladder because the item is about the unit, not driver behavior.

**Documentation is non-negotiable at every level.** Every action — even a 1st-occurrence coach — is logged with: date, driver name, incident description, 49 CFR citation (where applicable), expected behavior change, and driver signature (or refusal noted). Filed by Audra in Sharefile → incident file → by year → by driver.

**Drafting split:** Jeff Hannahs drafts written warning letters; Audra Newman files them and maintains the Sharefile record. Subject line pattern: driver first name only (e.g., "Brad") for inbox recognition.

**Insurance override:** Great West Casualty (via Acrisure / Jami Hewitt, jhewitt@acrisure.com) may independently require removal of a driver from covered equipment. That determination supersedes this policy at any level.

---

## Category 1 — HOS Violation

**Regulation:** 49 CFR Part 395 — Hours of Service of Drivers.

**What triggers it:** Samsara detects an HOS violation for the driver. Examples: driving beyond the 11-hour limit, exceeding the 14-hour on-duty window, violating the 30-minute break requirement, exceeding the 60/70-hour limit, or a short-haul exemption violation.

**FMCSA consequence:** HOS violations land directly on the HOS Compliance BASIC (80th percentile intervention threshold). A driver in violation at roadside is placed out of service on the spot. Violations stay on FMCSA MCMIS for 24 months (inspections) or 60 months (crashes).

**Decision tree:** Standard 4-tier warning ladder (Coach → Verbal → Written → Escalate).

**Severe-incident entry:** A roadside out-of-service order for HOS is a first-serious violation and may enter discipline at Level 3 (Strong Written Notice), bypassing the first two tiers. Management judges Level 3 vs. Level 4 based on severity and history.

---

## Category 2 — DVIR Defect

**Regulation:** 49 CFR Part 396.11 (pre-trip / post-trip inspection report) and 49 CFR Part 396.13 (driver's review of prior DVIR).

**What triggers it:** Driver files a DVIR (Driver Vehicle Inspection Report) and marks a defect. The defect must be repaired and signed off by a mechanic AND reviewed and certified by the next driver before the vehicle can be dispatched.

**FMCSA consequence:** A vehicle with an unrepaired DVIR defect that is dispatched is in violation of 49 CFR 396.11/396.13. At roadside, the vehicle may be placed out of service and a citation issued. Defects land on the CSA Vehicle Maintenance BASIC (80th percentile intervention threshold). The citation follows X-Trux's DOT number (841776) for 24 months.

**Decision tree:** Equipment-focused, not driver warning ladder. Action: repair immediately → verify signed off → dispatched unit checked. Escalate to Audra + ops management if unit dispatched with unrepaired defect.

---

## Category 3 — Coaching Needed / Needs Disposition

**Regulation:** No direct federal regulation on coaching itself, but underlying events (speeding, following distance, harsh braking, distracted driving) feed CSA Unsafe Driving BASIC (65th percentile intervention threshold).

**What triggers it (two sub-types):**

1. **Coaching Needed:** Driver has 2+ unacknowledged Samsara safety events in the last 30 days. The coaching program requires a session to be opened and completed. Ack state is derived from Samsara SafetyEvents sheet `coachingStatus` field (coached / dismissed / recognized = acked). NOT from the CoachingSessions sheet — that endpoint 404s for XFreight's account and the sheet is an empty placeholder.

2. **Needs Disposition:** Driver has an open coaching session (assigned) but it has not been closed / completed. Coaching sessions stay open until the status changes to coached/dismissed/recognized.

**14-day rule:** Unacknowledged coaching after 14 days = automatic Level 1 trigger (verbal counseling on failure to complete the coaching program). This is codified in `xfreight-progressive-discipline-policy.md` Section 5.

**Decision tree:** Standard 4-tier warning ladder applies to the coaching backlog, not just the underlying safety events. Drivers roll off the list after all events are acked, then for 3 more days (closeout indicator).

---

## Category 4 — DOT Inspection — Tractors

**Regulation:** 49 CFR Part 396.17 — Periodic inspection.

**What triggers it:** An active tractor in the fleet is past the XFreight 120-day company inspection policy. The brief's Equipment Compliance page (tractors) shows the unit with an OVERDUE badge on the 120-day window.

**The two windows (must not be conflated):**
- **120-day company policy:** Flagged as needing inspection. Unit remains in service — federally legal to run. Action: schedule inspection within 14 days.
- **365-day federal:** Out of service per FMCSA. Only triggered if the unit is 245+ days past the company 120-day policy. Almost never happens in normal operations.

**FMCSA consequence:** Inspection defects found at roadside land on the CSA Vehicle Maintenance BASIC (80th percentile threshold). Even if the federal 365d window has not elapsed, a unit with a known uncorrected defect dispatched to a roadside inspection will generate a citation. Inspection records stay 24 months on MCMIS.

**Ownership:** X-Trux Inc covers all DOT inspection costs regardless of entity holding title. Scheduling: Audra (safety/CSA piece); Dan + Jackson (Truk-Way tractor scheduling, coordination with dispatch).

**Decision tree:** Equipment-focused — schedule → inspect → update Alvys. Escalate if no action within 14 days.

---

## Category 5 — DOT Inspection — Trailers

**Regulation:** 49 CFR Part 396.17 — same as tractors.

**What triggers it:** An active trailer past the XFreight 120-day company inspection policy. Brief page 6 shows the unit OVERDUE.

**Same two-window rule as tractors.** Same language constraints (do not say "out of service" for 120d-only overdue).

**Ownership:** Dan + Jackson (trailers are Logistics, not Safety). Audra's brief filters trailers out of her action items — trailers appear only on the trailer page and the Logistics section.

**Decision tree:** Equipment-focused — schedule → inspect → update Alvys. Escalate if no action within 14 days.

---

## Category 6 — DVIR Compliance (Missing DVIRs)

**Regulation:** 49 CFR Part 396.11 (pre-trip/post-trip report required) and 49 CFR Part 396.13 (driver must review prior DVIR before driving).

**What triggers it:** Driver did not submit a DVIR for a trip. Missing DVIR = the driver failed to conduct or record the required inspection.

**FMCSA consequence:** Missing DVIR is a citable violation at roadside — automatic out-of-service if the vehicle has no current DVIR. Lands on CSA Vehicle Maintenance BASIC (80th percentile threshold). Unlike a repaired defect, a missing DVIR is a driver compliance failure, not a vehicle defect.

**Decision tree:** Standard 4-tier warning ladder. Missing DVIRs are a driver behavior issue (failure to follow procedure), not a vehicle defect issue.

---

## Category 7 — Prior Day Logs (Uncertified)

**Regulation:** 49 CFR Part 395.8 — driver must certify the previous day's electronic log within 24 hours.

**What triggers it:** Samsara shows the driver has uncertified prior-day logs. The driver has not signed/certified the ELD log for the prior day within the required window.

**FMCSA consequence:** Uncertified logs land on the HOS Compliance BASIC (80th percentile threshold). At roadside, an inspector can cite the driver for failure to maintain required records. The underlying HOS data may also be unverifiable without the certification, which can create additional citations.

**Decision tree:** Standard 4-tier warning ladder. Uncertified logs are a driver behavior issue (administrative compliance failure).

---

## Category 8 — Low Safety Score

**Regulation:** No direct 49 CFR regulation on the Samsara composite score itself, but underlying events (harsh braking, hard cornering, following distance, distracted driving, speeding) feed the CSA Unsafe Driving BASIC (65th percentile intervention threshold).

**What triggers it:** Driver's Samsara composite safety score falls below the defined threshold. The brief surfaces per-driver scores on page 3/4; the Teams card flags scores below the floor.

**Samsara fleet safety score:** Pulled from the per-driver safety-score endpoint (`/v1/fleet/drivers/{id}/safety-score` legacy path — the newer path 404s for XFreight's account). Scores are composite over a rolling period.

**Decision tree:** Standard 4-tier warning ladder. Low safety score is a pattern, not a single event. Coaching focus: identify which event types are driving the score down.

---

## Category 9 — Speeding

**Regulation:** 49 CFR Part 392.6 (drivers must not exceed speed limits); speed violations from roadside inspections land on CSA Unsafe Driving BASIC (65th percentile intervention threshold).

**What triggers it:** Driver's Samsara time-over-posted-limit percentage (% of drive time spent over the posted speed limit) triggers a comment in the speed rubric. Three windows computed: 6-month, 3-month, MTD. The peak of the three determines the flag.

**Speed-flag → discipline mapping (from `xfreight-progressive-discipline-policy.md` Section 4):**

| Peak % | Samsara comment | Accountability system entry |
|---|---|---|
| >= 3.0% | "STOP this driver now" | Level 2 minimum; Level 3 if prior speed history |
| >= 2.5% | "Need to sit down with this driver" | Level 1; Level 2 if no improvement in 30 days |
| >= 2.25% | "This is too fast" | Coaching (1st occurrence) |
| >= 2.0% | "Driver needs a conversation" | Coaching (1st occurrence) |
| >= 1.75% | "Where is the fire?" | Coach |
| >= 1.25% | "Watch this driver" | Coach |

**Bottom Line escalation:** Drivers named in the Bottom Line two consecutive weeks = automatic Level 2 regardless of trend. Exception: drivers showing "improving — keep it up" or "falling fast — keep it up" trend are excluded from Bottom Line escalation (still visible on page 4, but not named in the BL).

**Decision tree:** Standard 4-tier warning ladder, but entry point depends on the severity of the speed flag, not just occurrence count. "STOP this driver now" (>= 3%) enters at Level 2 minimum even on first occurrence.

---

## Documentation Standard (All Categories)

Every action — even a 1st-occurrence coach — must record:

1. Date of event + date of coaching/warning.
2. Driver name and truck number.
3. Incident description (what triggered the flag, from which data source).
4. 49 CFR Part citation (where applicable).
5. Expected behavior change and review date.
6. Driver signature or noted refusal.
7. Filed by Audra in Sharefile -> incident file -> by year -> by driver.
8. Jeff and JB retain working copies for Level 3+ (written warning or higher).

Subject line pattern: Driver first name only (e.g., "Brad") for inbox recognition.

---

## Key Personnel

- **Audra Newman** — Safety & AP owner. Primary actor on all 9 categories. Files all Sharefile records.
- **Dan Heeren + Jackson** — Logistics. Co-owners on Truk-Way tractor scheduling and all trailer categories.
- **Jeff Hannahs** — Drafts warning letters (Level 2+). CC on Level 3+.
- **JB Sweere** — Escalation target for Level 4+ and policy decisions.
- **Jami Hewitt (Acrisure / Great West Casualty)** — Insurance override authority at any level. Email: jhewitt@acrisure.com.

---

## CSA BASIC Threshold Reference

| BASIC | Intervention threshold | Categories affected |
|---|---|---|
| Unsafe Driving | 65th percentile | Speeding, Low Safety Score, Coaching Needed |
| Crash Indicator | 65th percentile | All |
| Vehicle Maintenance | 80th percentile | DVIR Defect, DVIR Compliance, DOT Inspection |
| HOS Compliance | 80th percentile | HOS Violation, Prior Day Logs |
| Driver Fitness | 80th percentile | Medical card / CDL issues |

Violations stay on FMCSA MCMIS for **24 months** (inspections/violations) or **60 months** (crashes).
