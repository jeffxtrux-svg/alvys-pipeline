---
title: Playbook — Customer Escalation
type: playbook
tags: [playbook, customers, sales, operations, dispute]
status: active
owner: "Jeff Hannahs (primary); Dan Heeren (ops context); JB Sweere (major concessions)"
last_revised: "2026-06-14"
trigger: "Customer relationship at risk — multi-load escalation, lawyer mentioned, 60+ days past due with no new tenders, invoice dispute >$5K, or MoM revenue drop >50%"
related: ["[[Customer Portfolio]]", "[[Risk Register]]", "[[Decision Journal]]", "[[Playbook — Driver Disciplinary]]", "[[Playbook — AR Follow-up]]", "[[Factoring]]"]
sources: ["raw/xfreight-playbook-customer-escalation.md"]
---

# Playbook — Customer Escalation

**When to run.** Any of:

- Customer email/call escalates beyond a single load issue (multiple loads cited, lawyer mentioned, "we need to talk about the relationship").
- A customer goes 60+ days past due **and** has stopped tendering new loads (silent walkaway).
- A customer disputes an invoice >$5K or files a chargeback through the factoring partner.
- A customer's MoM revenue drops >50% with no operational explanation.

**Goal.** Save the account if savable; if not, end the relationship cleanly — all AR collected, no FMCSA-reportable fallout.

**Pre-checks.**

1. Pull the customer's last 90 days of loads from Alvys (revenue, on-time %, claims).
2. Pull the customer's AR aging from QB (current, 31–60, 61–90, 91+). Cross-check [[Playbook — AR Follow-up]] status.
3. Check the SambaSafety / FMCSA file for any DOT-side issues that may be feeding the customer's perception.
4. Confirm who at the customer side is escalating (dispatcher / AP / VP) — determines who at XFreight responds.

---

## Steps

1. **Acknowledge within 4 business hours** — Jeff or Dan, whichever has the deeper relationship. Email or call back; name the issue specifically; set a meeting time within 48 hours. Do **not** promise a remedy on the first call.
2. **Internal pre-meeting** — Jeff + Dan + Audra (if safety/claims) review the load/AR/safety pull. Decide: defend, partial concede, full concede, or end.
3. **Customer meeting** — Jeff leads. Present XFreight's data; ask the customer for theirs. Listen for what they actually want (rate adjustment, ops fix, apology, exit).
4. **Document the agreement** — same day. Email summarizing what was agreed, deadlines, who owns each item. CC Dan (Ops) and Audra (AP) if money is involved.
5. **30-day follow-up** — Jeff schedules a check-in 30 days out to verify the fix held. Log in the run log below.

---

**Decision points.**

- **If the customer's data contradicts ours** — pause; get load-level proof (BOL, POD timestamps, Samsara location ping) before continuing.
- **If the issue is driver-specific behavior** — branch to [[Playbook — Driver Disciplinary]].
- **If the customer wants a rate change** — Jeff + JB decide; do not commit on the call.
- **If the customer is exiting** — switch to "clean exit" mode: collect all AR, recover trailers, no new tenders accepted. Log in [[Customer Portfolio]].

**Escalation.**

- JB (President) for any rate concession >5% or for a relationship over $200K/year of revenue.
- Outside counsel only if dispute >$25K or the customer threatens litigation.

**Capture.**

- Add an entry to the run log below.
- Recurring pattern (e.g., 3+ escalations cite the same driver) → add a risk to [[Risk Register]].
- Customer exits → update [[Customer Portfolio]]; add a [[Decision Journal]] entry: why the relationship ended, what we'd do differently.

---

## Recent Runs *(append-only)*

*(No run history yet — append as runs happen.)*

## Connections

- [[Customer Portfolio]] — track exits and relationship changes.
- [[Playbook — Driver Disciplinary]] — branch when the issue is driver behavior.
- [[Playbook — AR Follow-up]] — AR pauses during escalation; resumes when resolved.
- [[Risk Register]] — add concentration or recurring-escalation risks here.
- [[Decision Journal]] — log any concession decision or customer exit.

## Sources

- `raw/xfreight-playbook-customer-escalation.md`
