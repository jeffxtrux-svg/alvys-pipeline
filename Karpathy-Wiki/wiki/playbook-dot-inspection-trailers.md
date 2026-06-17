---
title: Playbook — DOT Inspection — Trailers
type: playbook
tags: [playbook, safety, compliance, dot, inspection, trailers, equipment, logistics]
status: active
owner: "Dan Heeren + Jackson (Logistics)"
last_revised: "2026-06-17"
trigger: "Brief's Equipment Compliance — Trailer Inspections page shows a trailer OVERDUE on the 120-day company policy"
related: ["[[DOT Inspection Policy]]", "[[Playbook — Equipment Inspection Backlog]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-dot-inspection-policy.md"]
---

# Playbook — DOT Inspection — Trailers

## 1. When to Run

Run this playbook when the Teams morning card or the daily email (Equipment Compliance — Trailer Inspections, page 6) shows a trailer with an OVERDUE badge on the **120-day company policy** pill. A trailer flagged here is **not out of service** — it is federally legal to run but past XFreight's voluntary more-conservative window.

**Ownership:** Trailers are a Logistics responsibility. Dan Heeren and Jackson own trailer inspection scheduling and dispatch coordination. Audra's brief filters trailers out of her action items — trailers do not appear in the Safety brief's equipment action items or the Risk Watch strip's safety-relevant signals. This playbook runs out of the Logistics workflow, not the Safety brief.

## 2. What This Means

49 CFR Part 396.17 requires annual DOT inspections (365-day interval) for trailers used in commercial transport. XFreight's voluntary **120-day company policy** is one-third the federal interval.

**The two windows — must not be conflated:**

| Window | Length | Status when OVERDUE | Language to use |
|---|---|---|---|
| 120-day company policy | 120 days from last inspection | Flagged as needing inspection; in service | "Needs inspection" / "flagged for inspection" — NOT "out of service" |
| 365-day federal (49 CFR 396.17) | 365 days from last inspection | Out of service per FMCSA | "Out of service" — reserved exclusively for this threshold |

A trailer would have to be **245+ days past** the 120-day policy to hit the federal 365-day limit. Under normal operations this essentially never happens.

FMCSA consequence: Inspection defects found on a trailer at roadside land on the **CSA Vehicle Maintenance BASIC** (intervention threshold: 80th percentile). The citation follows X-Trux's DOT number (841776) for **24 months** on FMCSA MCMIS, regardless of which entity holds the trailer title. Even if the federal annual window has not elapsed, a trailer with documented deferred maintenance is at higher risk of generating a citation if pulled over.

**Who pays:** X-Trux Inc covers all DOT inspection costs for every trailer regardless of which entity holds title or whether the trailer is being pulled by a company driver or an owner-operator.

**Why the 120-day policy:** Brake condition, tire wear, lighting, and structural integrity issues caught at 4 months vs. 12 months — earlier intervention means fewer in-service failures and lower CSA Maintenance BASIC exposure.

## 3. Decision Tree

Trailer inspections are an equipment action item, not a driver warning ladder.

| Situation | Action | Timeline | Who acts |
|---|---|---|---|
| Trailer OVERDUE on 120d policy | Schedule inspection with vendor | Within 14 days | Dan + Jackson |
| Trailer approaching 120d (within 14d) | Proactively schedule; avoid last-minute pull | Before OVERDUE | Dan + Jackson |
| Inspection scheduled but slot >14d out | Find second vendor or relocate trailer | Immediately | Dan + Jackson |
| Trailer OVERDUE and no action in 14d | Escalate to JB; consider pulling from dispatch | 14-day mark | Dan/Jackson → JB |
| Trailer OVERDUE on 365d federal | Unit is out of service — do not dispatch | Immediately | Dan/Jackson + JB + Acrisure notify |

## 4. Action Scripts

**Scheduling the inspection:**

> "[Vendor] — need to schedule a DOT inspection for trailer [unit #]. It's past our 120-day internal policy as of [date]. Available dates on our end: [options]. The trailer is currently assigned to [driver / load], expected back in [location] by [date]. Can you fit it in?"

**Coordinating with dispatch:**

> "Trailer [unit #] needs a DOT inspection before [target date]. It's currently [en route / in yard / assigned to driver X]. I'm holding it out of the next load assignment so we can get the inspection done. Available replacement trailers for any loads that were queued: [list]."

**Inspection complete — update Alvys:**

> Log the new inspection date in the trailer record in Alvys (`InspectionExpiresAt` field). Create a Maintenance record with Category = DOT/Annual. Confirm the update is in before the next Alvys pull so the brief reflects the correction.

**14-day no-action — escalate to JB:**

> "JB — trailer [unit #] has been past our 120-day inspection policy for [N] days without a scheduled inspection. [Describe obstacle.] Recommendation: [pull from dispatch / emergency vendor / other]. Need your call."

**Federal OOS (365d):**

> Unit does not move. Notify Acrisure. Update dispatch to use available equipment. JB makes cost/repair decision.

## 5. Documentation

- Date the trailer crossed the 120-day policy threshold.
- Scheduled inspection date and vendor.
- Date inspection was completed.
- Inspector name and certificate number.
- Updated in Alvys: trailer record `InspectionExpiresAt` + Maintenance record (Category: DOT/Annual).
- If escalated to JB: email or meeting note with date, unit, and decision made.
- If federal OOS: notify Acrisure in writing; retain documentation.

## 6. Decision Points

- **If the trailer is mid-route when the flag is spotted:** Do not pull mid-route on a 120d policy flag. Schedule on return. A 120d-overdue unit not near the federal 365d limit remains in service. Coordinate inspection for the next time the unit is in the yard.
- **If a trailer is leased to a driver or assigned to an OO:** Coordinate with the driver; their dispatch and pay may be affected. May involve the OO program (JB).
- **If the trailer fails inspection:** Unit stays out of service until repairs complete and re-inspection passes. Cost decision: repair vs. replace (JB decides for any amount above normal maintenance thresholds).
- **If multiple trailers are overdue simultaneously:** Triage by days-overdue, then dispatch criticality. If >8 trailers OVERDUE (brief's callout threshold), this is a fleet-level backlog. Run the [[Playbook — Equipment Inspection Backlog]] protocol alongside this one.
- **If vendor can't schedule within 14 days:** Find a second vendor or route the trailer through a region where a vendor has capacity.

## 7. Escalation

- **JB Sweere:** No action within 14 days; 365d federal OOS; cost-of-repair decision over threshold; any insurance notification requirement.
- **Audra Newman:** Loop in only if the inspection pattern creates a CSA Vehicle Maintenance BASIC concern — Audra tracks CSA implications across the fleet even though trailers are Logistics-owned. For routine scheduling, Audra is not the primary actor.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** 365d federal OOS event, or if the Vehicle Maintenance BASIC situation creates insurance exposure.

## 8. Connections

- [[DOT Inspection Policy]] — the canon on 120d vs 365d, who pays, language rules.
- [[Playbook — Equipment Inspection Backlog]] — fleet-level backlog response (use alongside this playbook when multiple trailers are overdue at once).
- [[Safety Program]] — equipment compliance page logic; how the two pills (120d/365d) are rendered in the brief.
- [[FMCSA CSA Scorecard]] — Vehicle Maintenance BASIC (80th percentile threshold).
- [[Key People]] — Dan Heeren + Jackson (primary owners), JB Sweere (cost decisions, escalation), Audra Newman (CSA oversight).

## 9. Recent Runs *(append-only)*

No runs logged yet.
