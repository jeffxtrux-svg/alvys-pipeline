---
title: Playbook — HOS Violation
type: playbook
tags: [playbook, safety, compliance, hos, hours-of-service, driver, accountability]
status: active
owner: "Audra Newman (Safety & AP)"
last_revised: "2026-06-17"
trigger: "Brief's Teams card shows an HOS Violation item for a driver, or Samsara flags an HOS event on pages 3/4 of the daily email"
related: ["[[Progressive Discipline Policy]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Coaching Ack]]", "[[Driver Roster]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-progressive-discipline-policy.md", "raw/xfreight-safety-program.md"]
---

# Playbook — HOS Violation

## 1. When to Run

Run this playbook when the Teams morning Adaptive Card or the daily scorecard email (pages 3–4) shows an HOS Violation flag for a driver. The badge in the Teams card tells you the occurrence count within the 30-day window, which determines the required action level. Also run if a DOT roadside inspection produces an HOS out-of-service order.

## 2. What This Means

Hours of Service rules (49 CFR Part 395) cap the amount of time a commercial driver can drive and be on duty per day and per week. Violations include: exceeding the 11-hour driving limit, the 14-hour on-duty window, the 30-minute break requirement, the 60/70-hour rolling limit, or a short-haul exemption condition. Samsara detects these from ELD data in near-real time.

FMCSA consequence: HOS violations land directly on the **HOS Compliance BASIC** (intervention threshold: 80th percentile). A driver caught in violation at roadside is placed out of service on the spot — the truck stops moving until the violation window expires. Violations stay on X-Trux's FMCSA MCMIS record (DOT #841776) for **24 months**. If the HOS Compliance BASIC approaches the 80th percentile, XFreight faces intervention risk including potential compliance reviews or targeted roadside inspections across the fleet.

A roadside out-of-service order for HOS is treated as a first-serious violation — it may bypass the first two coaching tiers and enter formal discipline at Level 3 (Strong Written Notice). Management sets the Level 3 vs. Level 4 entry point based on severity and history.

## 3. Decision Tree

| Occurrence in 30d | Signal in Teams card | Action required | Who acts |
|---|---|---|---|
| 1st | No badge / "1st" | Coach | Audra |
| 2nd | ⚠️ 2nd in 30d | Verbal warning | Audra |
| 3rd | 🔴 3rd in 30d | Written warning | Audra → Jeff drafts |
| 4th+ | 🚨 #N in 30d | Escalate to JB immediately | Audra → JB |
| Roadside OOS | Any | Enter at Level 3 minimum | Audra + JB consult |

**Mapping to formal discipline levels:** 1st (coach) = Level 1; 2nd (verbal) = Level 2; 3rd (written) = Level 3; 4th+ = Level 4 review. Level 4+ involves JB; Level 5 (load suspension / contract action / termination) requires JB decision.

## 4. Action Scripts

**1st — Coach (Level 1):**

> "I wanted to follow up on the HOS violation Samsara flagged on [date]. Under 49 CFR Part 395, we're required to keep driving time under 11 hours and on-duty time under 14 hours per day, and under 60/70 hours in 7/8 days. Please review your logs and let me know if something about your schedule made this hard to follow — I want to understand if there's a dispatch timing issue. I'm noting this conversation in your file. Going forward, if you're running close to your limits, call dispatch before you go over — never after."

**2nd — Verbal Warning (Level 2):**

> "This is the second HOS violation flagged in the last 30 days. Per our progressive discipline policy, this is a verbal warning — I'm documenting this conversation in your driver file now. A third violation within 30 days requires a written warning. HOS compliance is a federal requirement under 49 CFR Part 395; an inspector catching you in violation puts you out of service on the spot and puts our CSA score at risk. What do we need to change about your schedule or dispatch timing to prevent this?"

**3rd — Written Warning (Level 3):**

> Jeff drafts the letter. Subject line: "[Driver first name]". Cite 49 CFR Part 395, the specific violation(s), the dates of the prior two counseling/warning events, and the consequence of a fourth violation. Audra files original in Sharefile → incident file → by year → by driver. Jeff and JB retain working copies.

**4th+ — Escalate (Level 4):**

Contact JB Sweere directly. JB determines whether this triggers a load suspension (OO) or unpaid suspension (Truk-Way employee) and any insurance notification requirement.

## 5. Documentation

Record for every level:

- Date of the HOS event (from Samsara) and date of the coaching/warning conversation.
- Driver name, truck number, and brief description of the violation type.
- Citation: 49 CFR Part 395 (specify the rule — e.g., 395.3(a)(1) for the 11-hour limit).
- Expected behavior change (e.g., "call dispatch before going over limits; do not exceed 11-hour drive limit").
- Review date: 30 days from the coaching date.
- Driver signature (or "driver declined to sign, [date]").
- Filed: Sharefile → incident file → [year] → [driver name].
- CC Jeff and JB on Level 3+.

## 6. Decision Points

- **If the driver disputes the Samsara flag:** Pull the raw ELD log from the Samsara portal and compare to the driver's paper/electronic record. If Samsara's calculation is wrong (time zone error, personal conveyance miscategorized), note the dispute in the file and correct the flag. Do not issue discipline on a disputed flag until verified.
- **If the violation was caused by a dispatch instruction:** The dispatch instruction does not excuse the HOS violation — the driver is legally responsible for their own compliance — but it is a process failure. Note it in the file and loop in Dan to review the load-timing issue.
- **If this is a roadside OOS:** The event is already on FMCSA MCMIS. Contact Acrisure (Jami Hewitt) to flag the incident; insurance may have notification requirements. Enter discipline at Level 3 minimum.
- **If CSA HOS Compliance BASIC is approaching 80th percentile:** Accelerate discipline levels — flag to JB; issue a fleet-wide memo from Audra reinforcing HOS requirements.

## 7. Escalation

- **JB Sweere:** Level 4+ events; any roadside OOS; if HOS Compliance BASIC approaches 80th percentile.
- **Jeff Hannahs:** Drafted letter needed (Level 3+); CC on all Level 3+ actions.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** Notify for any roadside OOS event or if a driver's HOS pattern creates insurance exposure. Great West may independently require driver removal from covered equipment — that supersedes internal discipline.

## 8. Connections

- [[Progressive Discipline Policy]] — 5-level framework; speed-flag and coaching-backlog discipline mapping.
- [[Safety Program]] — HOS rubric, Samsara data sources, page-3 detail tables.
- [[FMCSA CSA Scorecard]] — HOS Compliance BASIC percentile threshold (80th).
- [[Coaching Ack]] — how coaching ack state is derived from Samsara SafetyEvents, not CoachingSessions.
- [[Driver Roster]] — active drivers; use to confirm fleet + entity (OO vs. Truk-Way employee) for track selection.
- [[Key People]] — Jeff Hannahs (drafts letters), Audra Newman (files + Sharefile), JB Sweere (Level 4+).

## 9. Recent Runs *(append-only)*

No runs logged yet.
