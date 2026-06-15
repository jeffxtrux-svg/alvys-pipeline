---
title: Playbook — Driver Disciplinary
type: playbook
tags: [playbook, safety, drivers, compliance, fmcsa]
status: active
owner: "Audra Newman (Safety — documentation + MVR); Dan Heeren (Ops coaching, company drivers); JB Sweere (OO separations)"
last_revised: "2026-06-14"
trigger: "Un-acked Samsara safety event >72h, two HOS violations in 30 days, driver named in customer escalation, DVIR defect unrepaired >7d, any DOT-recordable incident, MVR risk index change ≥2 categories"
related: ["[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Owner-Operator Program]]", "[[Driver Roster]]", "[[Risk Register]]", "[[Decision Journal]]", "[[Playbook — Customer Escalation]]", "[[Coaching Ack]]"]
sources: ["raw/xfreight-playbook-driver-disciplinary.md"]
---

# Playbook — Driver Disciplinary

**When to run.** Any of:

- A safety event (hard brake, harsh accel, speed-over-limit, crash) triggers a coaching session in Samsara that's still un-acked after 72 hours.
- Two HOS violations in a rolling 30-day window.
- A customer escalation cites a specific driver by name.
- A DVIR defect goes unrepaired past the company 7-day window.
- Any DOT-recordable incident (crash, roadside out-of-service, citation).
- An MVR risk index changes by ≥2 categories (SambaSafety alert).

**Goal.** Bring the driver back into compliance with the FMCSA/insurance documentation trail intact; if not coachable, separate cleanly with full paper trail.

**Pre-checks.**

1. Pull the driver's 90-day safety scorecard from Samsara (safety score, events, HOS violations, coaching ack rate). See [[Coaching Ack]] for how ack state is determined.
2. Pull the driver's recent MVR / license status from SambaSafety.
3. Pull the driver's settlement history (mileage, pay, last 4 weeks) — context for the conversation.
4. Confirm who the driver reports to (Dan = company driver; JB = OO-group; Audra = MVR/license).

---

## Steps

1. **Same-day documentation** — Audra (Safety) logs the trigger event in the driver file: date, severity, source data (event ID, customer email, DOT report number). No verbal-only steps.
2. **Coaching conversation within 5 business days** — Dan for ops issues, Audra for safety/MVR. Use the Samsara coaching workflow so the ack is recorded. Specific behavior, specific expectation, specific timeline.
3. **Written warning if repeated** — second incident of the same type within 60 days = formal written warning, signed by driver, filed in Sharefile (Audra's system). See [[Safety Program]] for the file structure.
4. **Performance improvement period** — 30 days of close monitoring (weekly Samsara review, weekly Dan check-in). Acceptance criteria written down upfront.
5. **Separation if no improvement** — JB + Audra decision. Final paycheck per SD law, termination letter on file; driver removed from Samsara/Alvys/SambaSafety; license/medical cert returned; truck/trailer/fuel card recovered.

---

**Decision points.**

- **If the trigger is a DOT-recordable incident** — Audra + JB review same day; may be a non-coachable separation depending on severity.
- **If the driver is an owner-operator (OO group)** — same playbook, but JB leads; separation = ending the lease, not employment.
- **If the driver disputes the data** — pull the underlying Samsara event JSON or DOT report; do not proceed off memory.
- **If 3+ drivers share the same root cause** — branch to a fleet-wide review; the issue is likely policy or equipment, not individual driver.

**Escalation.**

- JB for any separation.
- Outside counsel for any wrongful-termination signal or for OO-group lease termination.
- Insurance broker (Acrisure) within 48 hours of any DOT-recordable incident — pre-claim notice.

**Capture.**

- Append to the run log below (driver initials, date, trigger, outcome).
- Update [[Driver Roster]] if separation occurs.
- 3+ separations in 90 days → add a risk to [[Risk Register]] (driver-turnover signal).
- Recurring coaching pattern → add a [[Decision Journal]] entry: change the training, hiring, or equipment program.

---

## Recent Runs *(append-only)*

*(No run history yet — append as runs happen.)*

## Connections

- [[Safety Program]] — the full safety rubric, speed thresholds, and Sharefile file structure.
- [[Coaching Ack]] — how the brief derives the Ack column from Samsara SafetyEvents.
- [[FMCSA CSA Scorecard]] — DOT-recordable incidents land on the BASIC percentile ranks.
- [[Owner-Operator Program]] — lease termination differs from employment termination.
- [[Driver Roster]] — update on separation.
- [[Playbook — Customer Escalation]] — customer complaints about a specific driver branch here.

## Sources

- `raw/xfreight-playbook-driver-disciplinary.md`
