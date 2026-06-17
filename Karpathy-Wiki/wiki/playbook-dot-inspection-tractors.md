---
title: Playbook — DOT Inspection — Tractors
type: playbook
tags: [playbook, safety, compliance, dot, inspection, tractors, equipment, maintenance]
status: active
owner: "Audra Newman (Safety & AP — scheduling + CSA); Dan Heeren + Jackson (Truk-Way tractor dispatch coordination)"
last_revised: "2026-06-17"
trigger: "Brief's Equipment Compliance — Tractor Inspections page shows a tractor OVERDUE on the 120-day company policy"
related: ["[[DOT Inspection Policy]]", "[[Playbook — Equipment Inspection Backlog]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Progressive Discipline Policy]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-dot-inspection-policy.md", "raw/xfreight-progressive-discipline-policy.md"]
---

# Playbook — DOT Inspection — Tractors

## 1. When to Run

Run this playbook when the Teams morning card or the daily email (Equipment Compliance — Tractor Inspections, page 5) shows a tractor with an OVERDUE badge on the **120-day company policy** pill. This is the operational threshold XFreight works against. A tractor flagged here is **not out of service** — it is federally legal to run but past XFreight's voluntary more-conservative window.

Also run if a tractor triggers the 365-day federal pill (OVERDUE on the annual federal inspection), though this almost never happens given the 120d company policy catches units well before then.

## 2. What This Means

49 CFR Part 396.17 requires annual DOT inspections for commercial motor vehicles — every 12 months (365 days). XFreight's voluntary **120-day company policy** is one-third that interval. A tractor flagged OVERDUE here is past XFreight's company window, not the federal limit.

**The two windows — must not be conflated:**

| Window | Length | Status when OVERDUE | Language to use |
|---|---|---|---|
| 120-day company policy | 120 days from last inspection | Flagged as needing inspection; in service | "Needs inspection" / "flagged for inspection" — NOT "out of service" |
| 365-day federal (49 CFR 396.17) | 365 days from last inspection | Out of service per FMCSA | "Out of service" — reserved exclusively for this threshold |

A tractor would have to be **245+ days past** the 120-day policy to hit the federal 365-day limit. Under normal operations this essentially never happens — the company policy flags units early enough to schedule inspections before approaching the federal limit.

FMCSA consequence: If a tractor with unresolved inspection issues is pulled over at a roadside inspection and defects are found, the citations land on the **CSA Vehicle Maintenance BASIC** (intervention threshold: 80th percentile). Even if the federal 365-day annual window has not elapsed, a unit with documented deferred maintenance is at higher risk of generating a citation. Inspection defects stay on FMCSA MCMIS (DOT #841776) for **24 months**.

**Why XFreight runs the 120-day policy:** Driver safety (catch brake/tire/electrical issues at 4 months vs. 12 months), equipment longevity, CSA Maintenance BASIC protection, and operational scheduling (schedule between dispatches, not mid-route).

**Who pays:** X-Trux Inc covers all DOT inspection costs for every tractor regardless of which entity holds title and regardless of whether the tractor is pulled by a company driver or an owner-operator.

**Ownership split for Truk-Way tractors:** Audra owns the safety/CSA piece and drives scheduling. Dan + Jackson co-own the Truk-Way tractor scheduling and dispatch coordination. For X-Trux owner-operator tractors, Audra schedules; OO coordinates availability.

## 3. Decision Tree

Tractor inspections are an equipment action item, not a driver warning ladder.

| Situation | Action | Timeline | Who acts |
|---|---|---|---|
| Tractor OVERDUE on 120d policy | Schedule inspection with vendor | Within 14 days | Audra schedules; Dan/Jackson coordinate Truk-Way dispatch |
| Tractor approaching 120d (within 14d) | Proactively schedule; avoid last-minute pull | Before OVERDUE | Audra |
| Inspection scheduled but slot >14d out | Find second vendor or relocate unit | Immediately | Audra + ops |
| Tractor OVERDUE and no repair action in 14d | Escalate to JB; consider pulling from dispatch | 14-day mark | Audra → JB |
| Tractor OVERDUE on 365d federal | Unit is out of service — do not dispatch | Immediately | Audra + JB + Acrisure |

## 4. Action Scripts

**Scheduling the inspection:**

> "[Dan / Jackson] — tractor [unit #] is past due on our 120-day inspection policy as of [date]. I'm scheduling with [vendor]. Proposed inspection date: [date]. Can we work around dispatch for that unit? The inspection takes approximately [X] hours. I'll confirm with [vendor] and send you the slot."

**Inspection complete — update Alvys:**

> Log the new inspection date in the truck record in Alvys (`InspectionExpirationDate` field). Create a Maintenance record with Category = DOT/Annual. Confirm the record is updated before the next Alvys pull so the brief reflects the correction.

**14-day no-action — escalate:**

> "JB — tractor [unit #] has been past our 120-day inspection policy for [N] days with no scheduled inspection yet. [Describe the scheduling obstacle.] Recommendation: [pull from dispatch until inspected / authorize emergency vendor visit / other]. Your call on next steps."

**Federal OOS (365d) — immediate pull:**

> Unit does not move until inspected and signed off. Notify Acrisure. Update dispatch to route loads to available equipment. JB makes cost/repair decision.

## 5. Documentation

- Date the tractor crossed the 120-day policy threshold.
- Scheduled inspection date and vendor.
- Date inspection was completed.
- Inspector name and certificate number.
- Updated in Alvys: truck record `InspectionExpirationDate` + Maintenance record (Category: DOT/Annual).
- If escalated to JB: email or meeting note with date, unit, and decision made.
- If federal OOS: notify Acrisure in writing; retain documentation.

## 6. Decision Points

- **If the tractor is mid-route when the flag is spotted:** Do not pull mid-route on a 120d policy flag. Flag it as needing scheduling on return. A 120d-overdue unit that is not yet near the federal 365d limit remains in service. Coordinate the inspection for the next time the unit is in the yard.
- **If the tractor fails inspection:** Unit stays out of service until repairs are complete and re-inspection passes. Cost decision: repair vs. replace if over threshold (JB decides). OO-leased unit: coordinate with the OO on timeline and cost allocation.
- **If multiple tractors are overdue simultaneously:** Triage by days-overdue (most overdue first), then by dispatch criticality. Share prioritized list with Dan/Jackson same day. If >5 units OVERDUE, flag to [[Risk Register]] and [[Decision Journal]] as a process failure.
- **For Truk-Way tractors:** Action item owner is "Audra (Truk-Way tractors: shared w/ Dan + Jackson)." Both parties must be looped in — Audra for safety/CSA, Dan/Jackson for dispatch coordination. Until Alvys Trucks sheet carries `Truck.Fleet.Name`, action items in the brief cannot be split per-fleet.

## 7. Escalation

- **Dan Heeren + Jackson:** Every Truk-Way tractor scheduling action. Also for any X-Trux OO tractor that needs dispatch coordination.
- **JB Sweere:** No action within 14 days; 365d federal OOS; cost-of-repair decision (repair vs. replace) over threshold; any insurance notification requirement.
- **Jeff Hannahs:** CC if cost decision has P&L implications.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** 365d federal OOS event, or if the Vehicle Maintenance BASIC situation creates insurance exposure.

## 8. Connections

- [[DOT Inspection Policy]] — the canon on 120d vs 365d, who pays, language rules ("needs inspection" vs "out of service").
- [[Playbook — Equipment Inspection Backlog]] — broader multi-unit response when the backlog grows large; use that playbook for fleet-level triage.
- [[Safety Program]] — equipment compliance page logic; how the two pills (120d/365d) are rendered in the brief.
- [[FMCSA CSA Scorecard]] — Vehicle Maintenance BASIC (80th percentile threshold); inspection defects at roadside land here.
- [[Owner-Operator Program]] — OO-leased tractors are still covered under X-Trux inspection obligation.
- [[Key People]] — Audra Newman (scheduling, CSA), Dan Heeren + Jackson (Truk-Way dispatch coordination), JB Sweere (cost decisions, Level 4+).

## 9. Recent Runs *(append-only)*

No runs logged yet.
