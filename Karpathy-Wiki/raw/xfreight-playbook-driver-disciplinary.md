# Playbook — Driver disciplinary path (seed 2026-06-14)

> Source-of-record for the compiled `wiki/playbook-driver-disciplinary.md`.
> Captures how XFreight handles driver performance/safety issues from
> first incident through separation. Designed to be defensible to FMCSA,
> Samsara, and insurance reviews. Edit by appending; the librarian
> compiles the wiki page and keeps the run log.

**When to run.** Any of:
- A safety event (hard brake, harsh accel, speed-over-limit, crash) triggers a coaching session in Samsara that's still un-acked after 72 hours.
- Two HOS violations in a rolling 30-day window.
- A customer escalation cites a specific driver by name.
- A DVIR defect goes unrepaired past the company 7-day window.
- Any DOT-recordable incident (crash, roadside out-of-service, citation).
- An MVR risk index changes by ≥2 categories (SambaSafety alert).

**Goal.** Bring the driver back into compliance while keeping FMCSA/insurance documentation complete; if not coachable, separate cleanly with full paper trail.

**Pre-checks.**
1. Pull the driver's 90-day safety scorecard from Samsara (safety score, events, HOS violations, coaching ack rate).
2. Pull the driver's recent MVR / license status from SambaSafety.
3. Pull the driver's settlement history (mileage, pay, last 4 weeks) — context for the conversation.
4. Confirm who the driver reports to (Dan = company driver, JB = OO-group, Audra = MVR/license).

**Steps.**
1. **Same-day documentation** — Audra (Safety) logs the trigger event in the driver file: date, severity, source data (event ID, customer email, DOT report number). No verbal-only steps.
2. **Coaching conversation within 5 business days** — Dan for ops issues, Audra for safety/MVR. Use the Samsara coaching workflow so the ack is recorded in the system. Specific behavior, specific expectation, specific timeline.
3. **Written warning if repeated** — second incident of the same type within 60 days = formal written warning, signed by driver, kept in personnel file. Audra owns the file.
4. **Performance improvement period** — 30 days of close monitoring (weekly Samsara review, weekly Dan check-in). Acceptance criteria written down upfront.
5. **Separation if no improvement** — JB + Audra decision. Final paycheck handled per state law (SD), termination letter on file, driver removed from Samsara/Alvys/SambaSafety. License/medical cert returned. Trailer/truck/fuel card recovered.

**Decision points.**
- **If the trigger is a DOT-recordable** — Audra + JB review same day; this may be a non-coachable separation depending on severity.
- **If the driver is an owner-operator (OO group)** — same playbook, but JB leads (not Dan); separation = ending the lease, not employment.
- **If the driver disputes the data** — pull the underlying Samsara event JSON or DOT report; do not proceed off memory.
- **If pattern emerges (3+ drivers same root cause)** — branch to a fleet-wide review; the issue is likely policy or equipment, not driver.

**Escalation.**
- JB for any separation.
- Outside counsel for any wrongful-termination signal or for OO-group lease termination.
- Insurance broker (currently Acrisure) within 48 hours of any DOT-recordable incident — pre-claim notice.

**Capture.**
- Append to this playbook's run log (driver initials, date, trigger, outcome).
- Update `xfreight-driver-roster.md` if separation occurs.
- If 3+ separations in 90 days, add a risk to the risk register (driver turnover signal).
- If the same coaching pattern keeps emerging, add a decision-journal entry: change the program (training, hiring, equipment).

**Recent runs.** _(seed has no run history yet — append as runs happen)_
