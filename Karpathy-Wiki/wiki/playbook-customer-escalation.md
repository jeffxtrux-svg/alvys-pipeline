---
title: Playbook — Customer Escalation
type: playbook
tags: [playbook, customers, sales, ar, operations]
status: active
owner: Jeff Hannahs
last_revised: "2026-06-14"
trigger: "Customer escalation beyond a single load; 60+ day past-due with load silence; invoice dispute >$5K; MoM revenue drop >50%"
sources: ["raw/xfreight-playbook-customer-escalation.md"]
related: ["[[Customer Portfolio]]", "[[Playbook — Driver Disciplinary]]", "[[Playbook — AR Follow-up]]", "[[Decision Journal]]", "[[Risk Register]]"]
---

# Playbook — Customer Escalation

When a customer relationship is at risk: save the account if savable, exit cleanly if not.

## Trigger — When to Run

Any of:
- Customer email or call escalates beyond a single load issue — multiple loads cited, lawyer mentioned, or "we need to talk about the relationship."
- A customer goes **60+ days past due and has stopped tendering new loads** (silent walkaway).
- A customer disputes an invoice >$5K or files a chargeback through the factoring partner.
- A customer's MoM revenue drops >50% with no operational explanation.

## Goal

Save the account if savable. If not, end the relationship cleanly — full AR collected, no FMCSA-reportable fallout.

## Pre-Checks

1. Pull the customer's last 90 days of loads from Alvys (revenue, on-time %, claims).
2. Pull the customer's AR aging from QB (current, 31–60, 61–90, 91+).
3. Check the SambaSafety / FMCSA file for any DOT-side issues feeding the customer's perception.
4. Confirm who at the customer side is escalating — dispatcher / AP / VP — that determines who at XFreight responds.

## Steps

1. **Acknowledge within 4 business hours** — Jeff or Dan, whichever has the deeper relationship. Email or call back, name the issue specifically, set a meeting time within 48 hours. Do not promise a remedy on the first call.
2. **Internal pre-meeting** — Jeff + Dan + Audra (if safety/claims) review the load/AR/safety pull. Decide: defend, partial concede, full concede, or end.
3. **Customer meeting** — Jeff leads. Present the data XFreight has, ask for theirs. Listen for what they actually want (rate adjustment, ops fix, apology, exit).
4. **Document the agreement same day** — email summarizing what was agreed, deadlines, who owns each item. CC Dan (ops) and Audra (AP) if money is involved.
5. **30-day follow-up** — Jeff schedules a check-in 30 days out to verify the fix held. Log in this playbook's run log.

## Decision Points

- **If the customer's data contradicts ours** — pause, get the load-level proof (BOL, POD timestamps, Samsara location ping) before continuing.
- **If the issue is a driver-specific behavior** — branch to [[Playbook — Driver Disciplinary]].
- **If the customer wants a rate change** — Jeff + JB decide; do not commit on the call.
- **If the customer is exiting** — switch to clean-exit mode: collect all AR, recover trailers, no new tenders accepted.

## Escalation

- **JB** for any rate concession >5% or for a relationship over $200K/year of revenue.
- **Outside counsel** only if dispute >$25K or the customer threatens litigation.

## Capture

- Append an entry to this playbook's run log (below).
- If a recurring pattern emerges — e.g., 3+ escalations cite the same driver — add a risk to the [[Risk Register]].
- If the customer exits, update [[Customer Portfolio]] and add a [[Decision Journal]] entry: why the relationship ended, what we'd do differently.

## Connections

- [[Playbook — Driver Disciplinary]] — branch here if a specific driver is cited.
- [[Playbook — AR Follow-up]] — if the escalation is primarily about unpaid AR.
- [[Customer Portfolio]] — update account status if the outcome changes the relationship.
- [[Risk Register]] — "Customer concentration" risk; escalation patterns surface here.
- [[Decision Journal]] — exits and concessions are consequential decisions worth logging.

## Sources

- `raw/xfreight-playbook-customer-escalation.md` — seed 2026-06-14.

---

## Recent Runs

*(append-only log — never overwrite or reorder)*

*(No runs logged yet — append as escalations occur.)*
