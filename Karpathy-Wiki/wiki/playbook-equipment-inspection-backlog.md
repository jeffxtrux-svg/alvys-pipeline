---
title: Playbook — Equipment Inspection Backlog
type: playbook
tags: [playbook, safety, compliance, equipment, dot, tractors, trailers]
status: active
owner: "Audra Newman (tractors — X-Trux OO fleet solo; Truk-Way fleet shared w/ Dan Heeren); Dan Heeren (trailers)"
last_revised: "2026-06-14"
trigger: "Brief's Equipment Compliance page shows any unit OVERDUE on 120d company policy; roadside defect; new unit added to fleet"
sources: ["raw/xfreight-playbook-equipment-inspection-backlog.md"]
related: ["[[Safety Program]]", "[[Risk Register]]", "[[FMCSA CSA Scorecard]]", "[[Daily Scorecard Email]]", "[[Driver Roster]]", "[[Truk-Way Leasing]]", "[[Decision Journal]]"]
---

# Playbook — Equipment Inspection Backlog

Response to past-due tractor or trailer inspections flagged on the daily brief. Goal: every active unit back within the 120-day company policy within 14 days.

## Trigger — When to Run

- The brief's Equipment Compliance — Tractor Inspections page shows any unit **OVERDUE** badge on the **120d company policy** (the operational deadline).
- The brief's Equipment Compliance — Trailer Inspections page shows any unit **OVERDUE** badge on the **120d company policy**.
- A roadside inspection flags an inspection-related defect.
- A new truck or trailer comes onto the fleet — schedule the first inspection within 30 days.

> **What the two pills mean.** The brief shows two distinct pills per fleet type. "Annual inspection (365d federal): OVERDUE" means the unit is past the FMCSA rule and is out of service per federal — this almost never fires because of the 120d policy below. "DOT inspection (120d policy): OVERDUE" means past XFreight's voluntary, more-conservative threshold — the unit is still federally legal to run but needs scheduling. This playbook runs on the 120d threshold. See [[Safety Program]] for the full policy canon.

## Goal

Get every active unit back to current (within the 120d company policy) within **14 days**, with the inspection certificate logged in Alvys so the brief reflects it on the next refresh.

## Pre-Checks

1. Pull the brief's Equipment Compliance pages or read the `Alvys Pipeline.xlsx` Trucks + Trailers sheets directly.
2. Cross-check against Samsara Maintenance / DVIR feed — any unit with pending DVIR defects?
3. Confirm which units are actively dispatched (Dan/Logistics) — pulling a truck mid-trip needs coordination.
4. Check the maintenance vendor calendar — capacity for the next 14 days.

## Steps

1. **Triage by overdue days** — OVERDUE units first, then ≤30d-due, then 30–60d-due. Audra owns the prioritized list and shares with Dan same day.
2. **Schedule with the vendor** — Audra books inspection slots. Trailers often inspected at the yard; tractors go to the shop. Coordinate with Dan on dispatch timing.
3. **Units remain in service while scheduling** — units past the 120d company policy are flagged as needing inspection but stay in service. The 14-day window keeps them from drifting toward the federal 365d limit. Only at 245+ days past the 120d policy does a unit hit the federal limit. Trailers can typically finish their current load before the scheduled inspection; document any judgment call.
4. **Inspection performed** — vendor completes the inspection. Audra collects the certificate and invoice.
5. **Update Alvys** — log the new inspection date in the truck/trailer record (`InspectionExpirationDate` on trucks; `InspectionExpiresAt` on trailers). Create a Maintenance record with Category = DOT/Annual for the historical log.
6. **Verify on next refresh** — the next Alvys API pull (every 2 hours) updates `Alvys Pipeline.xlsx`. The next morning's brief will show the unit green.

## Decision Points

- **If the unit fails inspection** — repair before re-inspection. Tractor stays out of service until it passes. Cost decision: repair vs. replace if repair cost is material (JB decides).
- **If the vendor can't fit the unit within 14 days** — find a second vendor or move the unit to a different region. Don't run overdue without a plan.
- **If a trailer is leased to an owner-operator** — coordinate with the driver; their dispatch and pay are affected. May involve the OO program (JB).
- **If multiple units overdue simultaneously** — likely a process failure (calendar lapsed, vendor relationship lapsed). Add to [[Decision Journal]]: change the scheduling process.

## Escalation

- **Dan** if dispatch capacity is affected.
- **JB** if the cost of bringing units current is materially over budget, or if a major customer commitment is at risk because trucks are pulled.
- **Insurance broker (Acrisure)** heads-up if any unit has accumulated 30+ days past due — insurance may have notification requirements.

## Capture

- Append outcome to this playbook's run log (units brought current, days overdue at start, vendor cost, dispatch downtime in hours).
- Update the "Equipment inspection backlog" entry in the [[Risk Register]]: severity moves High → Medium when backlog is <5 units, → Low when fully current.
- If the backlog recurs 3+ months in a row with any past-due units, add to [[Decision Journal]]: change the scheduling tool or process.

## Connections

- [[Safety Program]] — 120d company policy and 365d federal threshold; the policy this playbook enforces.
- [[Risk Register]] — "Equipment inspection backlog" risk; this playbook is its response protocol.
- [[FMCSA CSA Scorecard]] — Maintenance BASIC percentile is affected by roadside inspection defects; inspection currency is the primary prevention.
- [[Daily Scorecard Email]] — pages 5–6 (Equipment Compliance) are the trigger source; the brief flags the units.
- [[Truk-Way Leasing]] — Truk-Way tractors are a shared Audra + Dan responsibility for maintenance; X-Trux OO tractors are Audra only.
- [[Decision Journal]] — repeated backlogs signal a process failure worth logging.

## Sources

- `raw/xfreight-playbook-equipment-inspection-backlog.md` — seed 2026-06-14.

---

## Recent Runs

*(append-only log — never overwrite or reorder)*

*(No runs logged yet — append as inspection backlogs are resolved.)*

---

## Current State (as of 2026-06-13)

- **4 tractors** past due on the 120d company policy (not federal 365d).
- **13 trailers** past due on the 120d company policy (not federal 365d).
- Owners: Audra (Safety) + Dan (Logistics / trailers).
- All DOT inspections covered by X-Trux Inc regardless of equipment title or driver assignment.
