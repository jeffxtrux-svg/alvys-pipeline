---
title: Playbook — AR Follow-up
type: playbook
tags: [playbook, ar, collections, finance, accounting]
status: active
owner: "Audra (AP/AR) — escalates to Jeff at 60d, JB at 85d"
last_revised: "2026-06-14"
trigger: "Any invoice in the 31-60 / 61-90 / 91+ aging buckets; any single invoice >$10K crossing 60 days"
related: ["[[Risk Register]]", "[[Decision Journal]]", "[[Factoring]]", "[[Active Disputes and Open Issues]]", "[[Daily Scorecard Email]]", "[[Playbook — Customer Escalation]]"]
sources: ["raw/xfreight-playbook-ar-followup.md"]
---

# Playbook — AR Follow-up (30 / 60 / 90 day)

**When to run.** Continuously, but each bucket has its own trigger:

- **31–60 days past due** — first formal nudge cycle.
- **61–90 days past due** — escalation cycle (Jeff involved).
- **91+ days past due** — pre-dispute / pre-factoring-recourse cycle (JB involved, factoring partner notified).
- Any single invoice >$10K crossing the 60-day mark, regardless of bucket totals.

**Goal.** Collect within the bucket without burning the relationship; for unsavable AR, move to dispute resolution or documented write-off.

**Pre-checks.**

1. Pull the QB AR Aging Detail report for X-Trux + X-Linx (JW Logistics excluded per [[JW Logistics]] policy).
2. Cross-check with the brief's QB-vs-Alvys reconciliation — is the invoice missing or duplicated?
3. Confirm the invoice was delivered to the customer (factoring partner or direct send).
4. Check whether an active dispute exists for this customer (see [[Active Disputes and Open Issues]]).

---

## Steps — 31–60 Bucket

1. **Day 31** — Audra sends a polite reminder referencing invoice number, amount, and original due date. Form letter; CC the dispatcher contact.
2. **Day 38** — If no response, phone call from Audra to the customer's AP contact.
3. **Day 45** — If still unpaid, escalate to the customer's dispatcher or account owner with a copy of the BOL/POD.
4. **Day 55** — If still unpaid, Audra hands to Jeff with a one-line context note → move to 61–90 triggers.

## Steps — 61–90 Bucket

1. **Day 61** — Jeff (BD) calls the customer's escalation point (usually VP/Controller, not AP). Frame as relationship preservation, not collections.
2. **Day 70** — Written follow-up with payment plan offer if cash is the issue. Acceptable: 50% within 14 days + remainder within 30. Anything longer → escalate.
3. **Day 85** — JB notified. Pre-decision: "collect aggressively" or "write-off planning"?

## Steps — 91+ Bucket

1. **Day 91** — Stop accepting new tenders from this customer pending resolution. Email confirmation to Dan (Ops) so dispatch is aligned.
2. **Day 95** — JB + Jeff + Audra meeting: dispute, collections agency, factoring recourse (if applicable), or write-off?
3. **Day 100** — Decision actioned. If factoring recourse: notify the partner per their contract terms. If collections: outside agency engaged with full documentation packet.
4. **Quarterly** — Review write-off list; any recovered amount reopens the customer-relationship discussion.

---

**Decision points.**

- **If the customer cites a service issue** — branch to [[Playbook — Customer Escalation]]; AR follow-up pauses pending resolution.
- **If the AR is on a factored invoice with recourse** — the factoring partner's contract clock starts; XFreight may owe the invoice back before the customer pays. See [[Factoring]].
- **If multiple customers from the same broker age together** — investigate broker-side payment delay, not individual customer issues.
- **If a customer enters bankruptcy** — immediate switch to creditor-claim mode; outside counsel.

**Escalation.**

- Jeff at 60 days.
- JB at 85 days.
- Outside counsel at 100 days or any disputed amount >$15K.
- Factoring partner notification per their recourse window (Pathward, Triumph, OTR, eCapital each have different terms — check the contract).

**Capture.**

- Append outcome to the run log below (customer, invoice, days, outcome, $ collected).
- Recurring pattern (same customer in 60+ bucket >once) → add to [[Risk Register]] as a concentration or AR-health risk.
- Process change triggered (move customer to upfront pay, switch factoring partner) → add to [[Decision Journal]].

---

## Recent Runs *(append-only)*

*(No run history yet — append as runs happen.)*

## Connections

- [[Risk Register]] — "AR aging / collections" entry; factoring onboarding risk.
- [[Factoring]] — recourse windows and partner terms.
- [[Playbook — Customer Escalation]] — AR pause branch when a service dispute is raised.
- [[Daily Scorecard Email]] — pages 11–13 show QB AR aging and the QB-vs-Alvys variance that feeds this playbook's trigger.

## Sources

- `raw/xfreight-playbook-ar-followup.md`
