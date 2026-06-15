---
title: Playbook — Equipment Inspection Backlog
type: playbook
tags: [playbook, safety, equipment, compliance, dot, inspections]
status: active
owner: "Audra Newman (Safety — 120d company-policy scheduling); Dan Heeren (Logistics — dispatch coordination)"
last_revised: "2026-06-14"
trigger: "Brief's Equipment Compliance page shows any unit with OVERDUE badge on the 120-day company policy; roadside inspection flags an inspection defect; new unit added to fleet"
related: ["[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Risk Register]]", "[[Decision Journal]]", "[[Daily Scorecard Email]]", "[[Owner-Operator Program]]"]
sources: ["raw/xfreight-playbook-equipment-inspection-backlog.md"]
---

# Playbook — Equipment Inspection Backlog

**When to run.** Triggered by:

- The brief's Equipment Compliance — Tractor Inspections page shows any unit with OVERDUE on the **120-day company policy** (the operational threshold — not the federal 365-day rule).
- The brief's Equipment Compliance — Trailer Inspections page shows any unit with OVERDUE on the **120-day company policy**.
- A roadside inspection flags an inspection-related defect.
- A new truck/trailer joins the fleet — schedule first inspection within 30 days.

> **Important:** The brief shows two pills per fleet type. "Annual inspection (365d federal): OVERDUE" means the unit is genuinely out-of-service per FMCSA. "DOT inspection (120d policy): OVERDUE" is XFreight's voluntary tighter window — the unit is **flagged as needing inspection** but remains federally legal in service. This playbook runs on the 120d threshold. A unit would have to be 245+ days past the 120d policy to hit the federal 365d limit. See `raw/xfreight-dot-inspection-policy.md` for the canon distinction. **Do not call a 120d-overdue unit "out of service."**

**Goal.** Get every active unit back to current inspection status (within the 120-day company policy) within 14 days, with documentation (sticker, invoice, maintenance record) logged in Alvys so the brief updates on the next refresh.

**Pre-checks.**

1. Pull the brief's Equipment Compliance pages, or read directly from `Alvys Pipeline.xlsx` Trucks + Trailers sheets.
2. Cross-check Samsara's Maintenance/DVIR feed — any unit with pending DVIR defects?
3. Confirm which units are actively dispatched (Dan/Logistics) — pulling a truck mid-trip needs coordination.
4. Check maintenance vendor calendar: capacity for the next 14 days.

---

## Steps

1. **Triage by overdue days** — units past the 120d company policy first, then ≤30d-due, then 30–60d-due. Audra owns the prioritized list and shares with Dan same day.
2. **Schedule with the vendor** — Audra books inspection slots. For trailers, the vendor often comes to the yard; for tractors, the truck goes to the shop. Coordinate with Dan on dispatch timing.
3. **Units past 120d company policy** — flagged as needing inspection, but remain in service while scheduling. Goal: inspect within 14 days so no unit drifts toward the federal 365d limit. Only at 245+ days past the 120d policy would a unit approach federal out-of-service status. Trailers can typically finish their current load; document any judgment call.
4. **Inspection performed** — vendor completes. Audra collects the certificate/invoice.
5. **Update Alvys** — log the inspection date in the truck/trailer record (`InspectionExpirationDate` on trucks, `InspectionExpiresAt` on trailers). Create a Maintenance record with Category = DOT/Annual for the history.
6. **Verify on next refresh** — next Alvys pull (every 2 hours since the June 2026 cadence bump) updates `Alvys Pipeline.xlsx`; next morning's brief shows the unit back to green.

---

**Decision points.**

- **If the unit fails inspection** — repair before re-inspection. Tractor stays out of service until passed. Cost decision: repair vs replace if repair >$X (JB decides).
- **If the vendor can't fit the unit in within 14 days** — find a second vendor or move the unit to a different region. Don't run on past-due indefinitely.
- **If a trailer is leased to a driver** — coordinate with the driver; their dispatch and pay are affected. May involve OO-program (JB).
- **If multiple units are overdue at once** — likely a process failure. Add to [[Decision Journal]]: change the scheduling tool/process.

**Escalation.**

- Dan if dispatch capacity is affected.
- JB if the cost of bringing units current is materially over budget, or if a major customer commitment is at risk because trucks are pulled.
- Insurance broker (Acrisure) heads-up if any unit has accumulated 30+ days past due — insurance may have notification requirements.

**Capture.**

- Append to the run log below (units brought current, days overdue at start, vendor cost, downtime in dispatch hours).
- Update "Equipment inspection backlog" in [[Risk Register]]: severity moves High → Medium when backlog <5 units, → Low when fully current.
- Backlog recurring 3+ months in a row → add to [[Decision Journal]]: change the scheduling tool/process.

---

## Recent Runs *(append-only)*

**2026-06-14 — Current state (seed snapshot from risk register):** 4 tractors and 13 trailers past due on the 120-day company policy (not the federal 365-day limit). Owners: Audra + Dan. All DOT inspections covered by X-Trux Inc regardless of equipment title or driver assignment. Playbook in effect as of this date.

## Connections

- [[Safety Program]] — DOT inspection policy, Sharefile records structure.
- [[FMCSA CSA Scorecard]] — inspection defects found roadside land on the Maintenance BASIC percentile.
- [[Risk Register]] — "Equipment inspection backlog" is an open High-severity risk.
- [[Owner-Operator Program]] — OO-leased units are still covered by X-Trux inspection obligation.

## Sources

- `raw/xfreight-playbook-equipment-inspection-backlog.md`
