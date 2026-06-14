# Playbook — Equipment inspection backlog response (seed 2026-06-14)

> Source-of-record for the compiled `wiki/playbook-equipment-inspection-backlog.md`.
> Captures the response when the brief's Equipment Compliance pages flag
> tractors or trailers past the federal 365-day annual inspection or the
> 120-day company DOT policy. Tied directly to the "Equipment inspection
> backlog" risk register entry.
> Edit by appending.

**When to run.** Triggered by:
- The brief's Equipment Compliance — Tractor Inspections page shows any unit with OVERDUE badge on Annual Inspection Due.
- The brief's Equipment Compliance — Trailer Inspections page shows any unit with OVERDUE badge on 120d Policy or Annual Inspection Due.
- A roadside inspection flags an inspection-related defect.
- A new truck/trailer comes onto the fleet — schedule the first inspection within 30 days.

**Goal.** Get every active unit back to current inspection status within 14 days, with the documentation (sticker, invoice, maintenance record) recorded in Alvys so the brief reflects it on the next refresh.

**Pre-checks.**
1. Pull the brief's Equipment Compliance pages or read directly from `Alvys Pipeline.xlsx` Trucks + Trailers sheets.
2. Cross-check against Samsara's Maintenance/DVIR feed — any unit with pending DVIR defects?
3. Confirm which units are actively dispatched right now (Dan/Logistics) — pulling a truck mid-trip needs coordination.
4. Check the maintenance vendor calendar — capacity at our usual shops for the next 14 days.

**Steps.**
1. **Triage by overdue days** — OVERDUE units first, then ≤30d-due, then 30-60d-due. Audra owns the prioritized list and shares with Dan same day.
2. **Schedule with the vendor** — Audra books inspection slots. For trailers, often the vendor comes to the yard; for tractors, the truck goes to the shop. Coordinate with Dan on dispatch timing.
3. **Pull from service if past due** — any tractor more than 0 days past the annual inspection is out of service per FMCSA. Dan reassigns loads. Trailers can sometimes finish their current load before pull-back (carrier judgment, document the decision).
4. **Inspection performed** — vendor completes inspection. Audra collects the certificate/invoice.
5. **Update Alvys** — log the inspection date in the truck/trailer record (`InspectionExpirationDate` field on trucks, `InspectionExpiresAt` on trailers — see the pipeline mapping). Also create a Maintenance record with Category = DOT/Annual for the historical log.
6. **Verify on next refresh** — the next Alvys API pull (every 2hr) should update `Alvys Pipeline.xlsx`. The next morning's brief will show the unit back to green.

**Decision points.**
- **If the unit fails inspection** — repair before re-inspection. Tractor stays out of service until passed. Cost decision: repair vs replace if repair >$X (JB decides).
- **If the inspection vendor can't fit the unit in within 14 days** — find a second vendor OR move the unit to a different region. Don't run on past-due.
- **If a trailer is leased to a driver** — coordinate with the driver; their dispatch and pay are affected. May involve OO-program (JB).
- **If multiple units overdue at the same time** — likely a process failure (forgot the calendar, vendor relationship lapsed). Add to decision journal: change the scheduling process.

**Escalation.**
- Dan if dispatch capacity is affected.
- JB if the cost of bringing units back current is materially over budget OR if a major customer commitment is at risk because trucks are pulled.
- Insurance broker (Acrisure) heads-up if any unit has accumulated 30+ days past due — insurance may have notification requirements.

**Capture.**
- Append outcome to this playbook's run log (units brought current, days overdue at start, vendor cost, downtime in dispatch hours).
- Update the "Equipment inspection backlog" risk register entry: severity moves from high → medium when the backlog is <5 units, → low when fully current.
- If the backlog keeps recurring (3+ months in a row with any past-due units), add to decision journal: change the scheduling tool/process.

**Recent runs.** _(seed has no run history yet — append as runs happen)_

**Current state (seed snapshot 2026-06-13 from the risk register).**
- 4 tractors past due on annual inspection.
- 13 trailers past due on annual inspection.
- Owners: Audra (Safety) + Dan (Logistics).
