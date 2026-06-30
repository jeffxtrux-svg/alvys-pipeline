---
title: Playbook — Driver Disciplinary
type: playbook
tags: [playbook, safety, drivers, compliance, fmcsa, hr]
status: active
owner: Audra Newman
last_revised: "2026-06-14"
trigger: "Un-acked coaching event >72h; two HOS violations in 30 days; DOT-recordable incident; MVR risk change ≥2 categories"
sources: ["raw/xfreight-playbook-driver-disciplinary.md"]
related: ["[[Safety Program]]", "[[Driver Roster]]", "[[Owner-Operator Program]]", "[[FMCSA CSA Scorecard]]", "[[Playbook — Customer Escalation]]", "[[Risk Register]]", "[[Decision Journal]]"]
---

# Playbook — Driver Disciplinary

Coaching through separation, with the FMCSA/insurance documentation trail intact.

## Trigger — When to Run

Any of:
- A safety event (hard brake, harsh accel, speed-over-limit, crash) triggers a Samsara coaching session still un-acked after **72 hours**.
- **Two HOS violations** in a rolling 30-day window.
- A customer escalation cites a **specific driver by name**.
- A DVIR defect goes unrepaired past the company **7-day window**.
- Any **DOT-recordable incident** (crash, roadside out-of-service, citation).
- An MVR risk index changes by **≥2 categories** (SambaSafety alert).

## Goal

Bring the driver back into compliance while keeping FMCSA/insurance documentation complete. If not coachable, separate cleanly with a full paper trail.

## Pre-Checks

1. Pull the driver's 90-day safety scorecard from Samsara (safety score, events, HOS violations, coaching ack rate).
2. Pull the driver's recent MVR / license status from SambaSafety.
3. Pull the driver's settlement history (mileage, pay, last 4 weeks) — context for the conversation.
4. Confirm who the driver reports to: **Dan** (company driver) · **JB** (OO-group) · **Audra** (MVR/license).

## Steps

1. **Same-day documentation** — Audra logs the trigger event in the driver file: date, severity, source data (Samsara event ID, customer email, DOT report number). No verbal-only steps.
2. **Coaching conversation within 5 business days** — Dan for ops issues, Audra for safety/MVR. Use the Samsara coaching workflow so the ack is recorded in the system. Specific behavior, specific expectation, specific timeline.
3. **Written warning if repeated** — second incident of the same type within 60 days = formal written warning, signed by driver, kept in personnel file. Audra owns the file.
4. **Performance improvement period** — 30 days of close monitoring (weekly Samsara review, weekly Dan check-in). Acceptance criteria written down upfront.
5. **Separation if no improvement** — JB + Audra decision. Final paycheck per SD state law, termination letter on file, driver removed from Samsara / Alvys / SambaSafety. License/medical cert returned. Trailer, truck, and fuel card recovered.

## Decision Points

- **If the trigger is a DOT-recordable** — Audra + JB review same day; may be a non-coachable separation depending on severity.
- **If the driver is an owner-operator (OO group)** — same playbook, but JB leads (not Dan); separation = ending the lease, not employment.
- **If the driver disputes the data** — pull the underlying Samsara event JSON or DOT report; do not proceed off memory.
- **If a pattern emerges (3+ drivers, same root cause)** — branch to a fleet-wide review; the issue is likely policy or equipment, not the individual driver.

## Escalation

- **JB** for any separation.
- **Outside counsel** for any wrongful-termination signal or OO-group lease termination.
- **Insurance broker (Acrisure)** within 48 hours of any DOT-recordable incident — pre-claim notice.

## Capture

- Append to this playbook's run log (driver initials, date, trigger, outcome).
- Update [[Driver Roster]] if separation occurs.
- If 3+ separations in 90 days, add a risk to the [[Risk Register]] (driver turnover signal).
- If the same coaching pattern keeps recurring, add a [[Decision Journal]] entry: change the program (training, hiring, equipment).

## Connections

- [[Safety Program]] — speed-over-limit rubric, coaching policy, MVR workflow, and the discipline framework this playbook operationalizes.
- [[Driver Roster]] — updated when a driver separates.
- [[Owner-Operator Program]] — OO-group separation is a lease end, not employment; JB leads.
- [[FMCSA CSA Scorecard]] — repeated events can move BASIC percentiles; flag to Audra when that link appears.
- [[Playbook — Customer Escalation]] — branch here if a customer complaint cites a specific driver.
- [[Risk Register]] — "Driver turnover" risk; feeds here if 3+ separations in 90 days.
- [[Decision Journal]] — recurring patterns are consequential decisions about the training/hiring program.

## Sources

- `raw/xfreight-playbook-driver-disciplinary.md` — seed 2026-06-14.

---

## Recent Runs

*(append-only log — never overwrite or reorder)*

*(No runs logged yet — append as disciplinary actions occur.)*
