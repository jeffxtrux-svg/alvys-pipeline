---
title: Playbook — DVIR Defect
type: playbook
tags: [playbook, safety, compliance, dvir, defect, equipment, maintenance]
status: active
owner: "Audra Newman (Safety & AP); ops (dispatch coordination)"
last_revised: "2026-06-17"
trigger: "Brief's Teams card shows a DVIR Defect item for a driver/unit — driver filed a DVIR with a defect marked"
related: ["[[Progressive Discipline Policy]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Playbook — Equipment Inspection Backlog]]", "[[DOT Inspection Policy]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-progressive-discipline-policy.md", "raw/xfreight-safety-program.md"]
---

# Playbook — DVIR Defect

## 1. When to Run

Run this playbook when the Teams morning card or the daily email (page 3 — Safety & Compliance Detail) shows a DVIR Defect flag for a driver/unit. A DVIR defect means the driver found a mechanical or safety problem during their pre-trip or post-trip inspection and logged it on the Driver Vehicle Inspection Report. The defect stays flagged until a mechanic signs it off as repaired and the next driver certifies they reviewed it.

Unlike driver behavior items (HOS, speeding), a DVIR defect is primarily a **vehicle/equipment action item** — get the unit repaired and certified. If a defective unit was nonetheless dispatched, that is a separate compliance failure that requires the driver warning ladder.

## 2. What This Means

Under 49 CFR Part 396.11, drivers must submit a DVIR at the end of every trip noting any defects or deficiencies. Under 49 CFR Part 396.13, the next driver must review the prior DVIR before operating the vehicle. If a defect is noted, it must be repaired (or the unit must be certified as not needing repair) and the mechanic must sign the DVIR before the vehicle returns to service.

FMCSA consequence: Dispatching a vehicle with an unrepaired DVIR defect is a direct violation of 49 CFR 396.11/396.13. At a roadside inspection, the vehicle may be placed out of service on the spot and a citation issued against X-Trux's DOT number (841776). Defect-related citations land on the **CSA Vehicle Maintenance BASIC** (intervention threshold: 80th percentile). Inspection records stay on FMCSA MCMIS for **24 months**. Repeated Vehicle Maintenance BASIC accumulation can trigger a compliance review of the entire fleet.

## 3. Decision Tree

DVIR defects use an equipment-focused response, not the standard driver warning ladder. The priority is restoring the unit to safe, documented operating condition.

| Situation | Action | Timeline | Who acts |
|---|---|---|---|
| Defect logged, unit not yet dispatched | Route to mechanic immediately; do not dispatch until signed off | Same shift | Ops + maintenance |
| Defect repaired + mechanic sign-off | Confirm next driver reviews prior DVIR before dispatch | Before next dispatch | Dispatch + driver |
| Defect open > 24h with no repair action | Escalate to Audra; unit pulled from available dispatch | 24h | Audra + ops |
| Unit dispatched with known unrepaired defect | Treat as serious compliance failure; enter discipline at Level 3+ | Immediately | Audra + JB |
| Roadside OOS for DVIR defect | Notify Acrisure; enter discipline at Level 3+ | Immediately | Audra + JB |

**If a driver is repeatedly reporting defects and the unit keeps going out with unresolved issues**, the problem may be in the maintenance workflow, not driver behavior. Address the maintenance process first; document the pattern.

**If a driver knowingly drove a unit with an unrepaired defect without reporting it**, that is a falsification issue — a potential immediate termination ground (falsifying regulatory records under the immediate-termination clause in the progressive discipline policy).

## 4. Action Scripts

**Routine defect — coordinate with ops and maintenance:**

> "The DVIR from [driver name] on [date] shows [defect description] on unit [truck/trailer number]. Unit is pulled from dispatch until we get the mechanic sign-off. Ops — please route any pending loads for that unit to available equipment. [Mechanic/vendor] — need this repaired and signed before next dispatch. I'll confirm the next driver reviews the cleared DVIR before the truck goes out."

**Defect open >24h — escalate:**

> "The DVIR defect logged on [date] for unit [#] is now more than 24 hours without repair sign-off. I'm pulling the unit from available dispatch until this is resolved. [Ops name] — please confirm no loads are assigned to this unit. If there's a resource issue preventing the repair, let me know so we can arrange a vendor visit."

**Unit dispatched with unrepaired defect — Level 3+ discipline:**

> Jeff drafts the notice. Cite 49 CFR Part 396.11/396.13, the defect description, the date the defect was logged and not yet signed off, and the date the unit was dispatched. Audra files original in Sharefile → incident file → by year → by driver. Jeff and JB retain working copies.

## 5. Documentation

For the equipment action:

- Date the defect was logged, defect description, unit number.
- Date repair was completed and mechanic's name/signature.
- Date next driver certified review of the cleared DVIR.
- Updated in Alvys maintenance record for the unit.

For any discipline action (dispatching with known defect):

- Date of defect, date of dispatch, driver name, truck/trailer number.
- Citation: 49 CFR Part 396.11 / 396.13.
- Expected behavior change.
- Driver signature or noted refusal.
- Filed: Sharefile → incident file → [year] → [driver name].
- CC Jeff and JB on Level 3+.

## 6. Decision Points

- **If the defect is cosmetic / non-safety-critical:** Mechanic must still sign off. The decision about whether a defect needs repair vs. "does not affect safe operation" is the mechanic's to make in writing — not the driver's or dispatcher's.
- **If the driver disputes that they drove with a known defect:** Pull the dispatch logs and DVIR timestamps to establish the sequence. Document the findings.
- **If the CSA Vehicle Maintenance BASIC is approaching 80th percentile:** Flag to JB; consider a fleet-wide pre-trip memo from Audra. If already above 60th percentile, any driver generating an additional Maintenance citation skips to Level 3 entry per the progressive discipline policy.
- **If multiple DVIR defects on the same unit in a short window:** The unit may have an underlying mechanical issue. Flag to Dan/Jackson for maintenance review — this is also an [[Playbook — Equipment Inspection Backlog]] trigger.

## 7. Escalation

- **JB Sweere:** Unit dispatched with unrepaired defect; roadside OOS event; Vehicle Maintenance BASIC approaching 80th percentile.
- **Jeff Hannahs:** Drafted discipline letter needed (Level 3+); CC on all Level 3+ actions.
- **Dan Heeren / Jackson:** Dispatch coordination when a unit is pulled; maintenance scheduling for Truk-Way tractors.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** Notify for any roadside OOS event. Great West may independently require driver removal from covered equipment.

## 8. Connections

- [[Progressive Discipline Policy]] — Level 3+ entry for dispatching with known defect; immediate termination grounds for falsification.
- [[Safety Program]] — DVIR defect tracking in Samsara, page-3 detail.
- [[FMCSA CSA Scorecard]] — Vehicle Maintenance BASIC (80th percentile threshold).
- [[Playbook — Equipment Inspection Backlog]] — overlapping trigger: unit with repeated DVIR defects may have a deeper maintenance / inspection need.
- [[DOT Inspection Policy]] — 120d company policy vs 365d federal; language rules.
- [[Key People]] — Audra Newman (owner), Jeff Hannahs (drafts letters), JB Sweere (Level 4+), Dan/Jackson (dispatch + maintenance coordination).

## 9. Recent Runs *(append-only)*

No runs logged yet.
