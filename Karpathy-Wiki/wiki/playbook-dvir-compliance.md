---
title: Playbook — DVIR Compliance (Missing DVIRs)
type: playbook
tags: [playbook, safety, compliance, dvir, missing, pre-trip, driver, accountability]
status: active
owner: "Audra Newman (Safety & AP)"
last_revised: "2026-06-17"
trigger: "Brief's Teams card shows a DVIR Compliance item for a driver — driver did not submit a required DVIR for a trip"
related: ["[[Progressive Discipline Policy]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Playbook — DVIR Defect]]", "[[Driver Roster]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-progressive-discipline-policy.md", "raw/xfreight-safety-program.md"]
---

# Playbook — DVIR Compliance (Missing DVIRs)

## 1. When to Run

Run this playbook when the Teams morning card or the daily email (page 3 — Safety & Compliance Detail) shows a DVIR Compliance flag for a driver. This means the driver did not submit a Driver Vehicle Inspection Report for a trip — they either skipped the pre-trip/post-trip inspection entirely or completed it but failed to record and submit it in the ELD system.

This is distinct from [[Playbook — DVIR Defect]], which covers what happens when a driver files a DVIR and marks a defect. DVIR Compliance is about the missing report itself — a driver behavior and compliance failure, not a vehicle defect.

## 2. What This Means

49 CFR Part 396.11 requires drivers to prepare a written report (DVIR) at the end of each day that the vehicle was operated, covering required inspection points (brakes, lights, tires, steering, etc.). 49 CFR Part 396.13 requires the next driver to review the prior DVIR before operating the vehicle and certify that they reviewed it.

FMCSA consequence: A missing DVIR is a citable violation on its own — it is a failure to maintain required records. At a roadside inspection, an inspector who asks for the DVIR and finds it missing can issue an automatic out-of-service order. This is different from a defect out-of-service: the vehicle itself may be mechanically fine, but the paper/electronic compliance trail is broken. Citations land on the **CSA Vehicle Maintenance BASIC** (intervention threshold: 80th percentile). Missing-DVIR citations stay on FMCSA MCMIS (DOT #841776) for **24 months**.

Unlike a discovered defect (which can be repaired), a missing DVIR cannot be retroactively corrected — the inspection window has passed. The only remediation is driver behavior change going forward.

## 3. Decision Tree

Missing DVIRs are a driver behavior failure, so the standard 4-tier warning ladder applies.

| Occurrence in 30d | Signal in Teams card | Action required | Who acts |
|---|---|---|---|
| 1st | No badge / "1st" | Coach | Audra |
| 2nd | ⚠️ 2nd in 30d | Verbal warning | Audra |
| 3rd | 🔴 3rd in 30d | Written warning | Audra → Jeff drafts |
| 4th+ | 🚨 #N in 30d | Escalate to JB immediately | Audra → JB |

**Severity note:** A roadside out-of-service for a missing DVIR at a critical checkpoint may jump directly to Level 3 (Strong Written Notice) regardless of occurrence count. Management judgment applies.

## 4. Action Scripts

**1st — Coach (Level 1):**

> "I'm following up on the missing DVIR from [date]. Under 49 CFR Part 396.11, every driver must complete and submit a vehicle inspection report after every trip — this is a federal requirement, not an optional form. If the inspector pulls you over and can't see your DVIR, you get placed out of service on the spot. Going forward, submit your DVIR in the Samsara app immediately after every pre-trip and post-trip inspection, before you move the truck. Do you have any questions about how to file it in the app?"

**2nd — Verbal Warning (Level 2):**

> "This is the second missed DVIR in 30 days. Per our progressive discipline policy, this is a verbal warning. I'm documenting this conversation in your file now. A third missed DVIR in 30 days requires a written warning. The DVIR is not optional — it's a federal regulation, and a missing one gets you placed out of service at roadside. I want to understand what's getting in the way. Is there a process issue or an ELD issue that's making the submission harder?"

**3rd — Written Warning (Level 3):**

> Jeff drafts the letter. Subject line: "[Driver first name]". Cite 49 CFR Part 396.11, the specific dates of the missed DVIRs, the prior verbal warning date, and the consequence of continued non-compliance. Audra files original in Sharefile → incident file → by year → by driver. Jeff and JB retain working copies.

**4th+ — Escalate:**

Contact JB Sweere directly. JB determines next step (load suspension for OO; unpaid suspension for Truk-Way employee).

## 5. Documentation

Record for every level:

- Date(s) the DVIR was missing (from Samsara).
- Driver name, truck/trailer number, and trip information.
- Citation: 49 CFR Part 396.11 (pre-trip/post-trip DVIR requirement).
- Expected behavior change (e.g., "submit DVIR in Samsara immediately after every inspection, every trip, no exceptions").
- Review date: 30 days.
- Driver signature (Level 2+) or "driver declined to sign, [date]".
- Filed: Sharefile → incident file → [year] → [driver name].
- CC Jeff and JB on Level 3+.

## 6. Decision Points

- **If the driver claims the DVIR was submitted but the system didn't capture it:** Pull the Samsara ELD log to check. If it was a system error, document the investigation outcome and do not issue discipline. Fix the system issue. If no record exists in Samsara, the burden is on the driver to show otherwise.
- **If the driver is new or just started using the ELD system:** Consider whether additional ELD training is the right first step. Still document the conversation, but a training-focused response may be more appropriate than a disciplinary response for a first occurrence.
- **If the pattern is specific to certain days or routes:** Look for a systemic issue — does this driver always miss DVIRs after certain load types or destinations? Might indicate a workflow issue worth correcting at the dispatch level.
- **If the CSA Vehicle Maintenance BASIC is approaching 80th percentile:** Accelerate discipline — missing DVIRs that generate citations at roadside will push the BASIC higher. Flag to JB. If already above 60th percentile, any subsequent citation skips to Level 3 entry per the progressive discipline policy.
- **If the driver receives a roadside out-of-service for a missing DVIR:** Treat as a first-serious violation — may enter at Level 3 regardless of prior occurrence count. Notify Acrisure.

## 7. Escalation

- **JB Sweere:** 4th+ occurrence; roadside OOS for missing DVIR; Vehicle Maintenance BASIC approaching 80th percentile.
- **Jeff Hannahs:** Level 3 written warning draft; CC on Level 3+.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** Roadside OOS event. Great West may independently require removal from covered equipment.

## 8. Connections

- [[Playbook — DVIR Defect]] — the sibling playbook for when a DVIR is submitted and marks a defect. The two playbooks address different problems: this one is about missing reports; the Defect playbook is about the reported defect itself.
- [[Progressive Discipline Policy]] — 5-level framework; incomplete DVIR is listed as a Level 1 trigger for first minor incident.
- [[Safety Program]] — DVIR defect / compliance tracking in Samsara, page-3 detail.
- [[FMCSA CSA Scorecard]] — Vehicle Maintenance BASIC (80th percentile threshold).
- [[Driver Roster]] — active drivers; check OO vs. Truk-Way track for discipline track selection.
- [[Key People]] — Audra Newman (owner), Jeff Hannahs (drafts letters), JB Sweere (Level 4+).

## 9. Recent Runs *(append-only)*

No runs logged yet.
