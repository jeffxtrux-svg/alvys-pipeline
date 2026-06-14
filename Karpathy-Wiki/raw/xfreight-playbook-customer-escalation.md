# Playbook — Customer escalation (seed 2026-06-14)

> Source-of-record for the compiled `wiki/playbook-customer-escalation.md`.
> Captures XFreight's response pattern when a customer is unhappy enough
> that the relationship is at risk. Edit by appending; the librarian will
> compile the wiki page and keep the run log in sync.

**When to run.** Any of:
- Customer email/call escalates beyond a single load issue (multiple loads cited, lawyer mentioned, "we need to talk about the relationship").
- A customer goes 60+ days past due **and** has stopped tendering new loads (silent walkaway).
- A customer disputes an invoice >$5K or files a chargeback through the factoring partner.
- A customer's MoM revenue drops >50% with no operational explanation.

**Goal.** Save the account if savable; if not, end the relationship cleanly with full AR collected and no FMCSA-reportable fallout.

**Pre-checks.**
1. Pull the customer's last 90 days of loads from Alvys (revenue, on-time %, claims).
2. Pull the customer's AR aging from QB (current, 31-60, 61-90, 91+).
3. Check the SambaSafety / FMCSA file for any DOT-side issues that may be feeding the customer's perception.
4. Confirm who at the customer side is escalating (the dispatcher / the AP person / the VP) — that determines who at XFreight responds.

**Steps.**
1. **Acknowledge within 4 business hours** — Jeff or Dan, whichever has the deeper relationship. Email or call back, name the issue specifically, set a meeting time within 48 hours. Do not promise a remedy on the first call.
2. **Internal pre-meeting** — Jeff + Dan + Audra (if safety/claims) review the load/AR/safety pull. Decide: defend, partial concede, full concede, or end.
3. **Customer meeting** — Jeff leads. Present the data XFreight has, ask the customer for theirs. Listen for what they actually want (rate adjustment, ops fix, apology, exit).
4. **Document the agreement** — same day. Email summarizing what was agreed, deadlines, who owns each item. CC Dan (ops) and Audra (AP) if money is involved.
5. **30-day follow-up** — Jeff schedules a check-in 30 days out to verify the fix held. Log in this playbook's run log.

**Decision points.**
- **If the customer's data contradicts ours** — pause, get the load-level proof (BOL, POD timestamps, Samsara location ping) before continuing.
- **If the issue is a driver-specific behavior** — branch to the driver-disciplinary playbook.
- **If the customer wants a rate change** — Jeff + JB decide; do not commit on the call.
- **If the customer is exiting** — switch to "clean exit" mode: collect all AR, recover trailers, no new tenders accepted.

**Escalation.**
- JB (President) for any rate concession >5% or for a relationship over $200K/year of revenue.
- Outside counsel only if dispute >$25K or the customer threatens litigation.

**Capture.**
- Add an entry to this playbook's run log below.
- If a recurring pattern emerges (e.g., 3+ escalations cite the same driver), add a risk to the risk register.
- If the customer exits, update `xfreight-customer-portfolio.md` and add a decision-journal entry: why the relationship ended, what we'd do differently.

**Recent runs.** _(seed has no run history yet — append as runs happen)_
