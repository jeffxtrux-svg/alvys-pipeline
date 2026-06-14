# Playbook — Equipment inspection backlog response (seed 2026-06-14)

> Source-of-record for the compiled `wiki/playbook-equipment-inspection-backlog.md`.
> Captures the response when the brief's Equipment Compliance pages flag
> tractors or trailers past the federal 365-day annual inspection or the
> 120-day company DOT policy. Tied directly to the "Equipment inspection
> backlog" risk register entry.
> Edit by appending.

**When to run.** Triggered by:
- The brief's Equipment Compliance — Tractor Inspections page shows any unit with OVERDUE badge on the **120d company policy** (the operational deadline; this is the badge that drives this playbook).
- The brief's Equipment Compliance — Trailer Inspections page shows any unit with OVERDUE badge on the **120d company policy**.
- A roadside inspection flags an inspection-related defect.
- A new truck/trailer comes onto the fleet — schedule the first inspection within 30 days.

> Important: the brief's two pills mean different things. **"Annual inspection (365d federal): OVERDUE"** is the FMCSA rule — only triggered when a unit is 245+ days past the company 120d policy and is genuinely out-of-service per federal. **"DOT inspection (120d policy): OVERDUE"** is the XFreight policy — operationally past due but still federally legal. This playbook runs on the 120d company-policy threshold; see `xfreight-dot-inspection-policy.md` for the canon distinction.

**Goal.** Get every active unit back to current inspection status (within the 120d company policy) within 14 days, with the documentation (sticker, invoice, maintenance record) recorded in Alvys so the brief reflects it on the next refresh.

**Pre-checks.**
1. Pull the brief's Equipment Compliance pages or read directly from `Alvys Pipeline.xlsx` Trucks + Trailers sheets.
2. Cross-check against Samsara's Maintenance/DVIR feed — any unit with pending DVIR defects?
3. Confirm which units are actively dispatched right now (Dan/Logistics) — pulling a truck mid-trip needs coordination.
4. Check the maintenance vendor calendar — capacity at our usual shops for the next 14 days.

**Steps.**
1. **Triage by overdue days** — OVERDUE units first, then ≤30d-due, then 30-60d-due. Audra owns the prioritized list and shares with Dan same day.
2. **Schedule with the vendor** — Audra books inspection slots. For trailers, often the vendor comes to the yard; for tractors, the truck goes to the shop. Coordinate with Dan on dispatch timing.
3. **Schedule before federal exposure** — units past the 120d company policy are NOT out of service per FMCSA (federal is 365d), but they should be inspected within the 14-day window so no unit drifts toward the federal 365d limit. If a unit ever crosses 245 days past the 120d policy it would be at the federal limit — escalate immediately and pull from service. Trailers can typically finish their current load before scheduled inspection; document any judgment call.
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
- 4 tractors past due **on the 120d company policy** (not federal 365d).
- 13 trailers past due **on the 120d company policy** (not federal 365d).
- Owners: Audra (Safety) + Dan (Logistics).
- All DOT inspections covered by X-Trux Inc regardless of equipment title or driver assignment.
