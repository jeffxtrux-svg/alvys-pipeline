---
title: Playbook — Factoring Partner Switch
type: playbook
tags: [playbook, finance, factoring, cash-flow]
status: active
owner: "JB Sweere (sign-off); Jeff Hannahs (BD / partner coordination); Audra Newman (customer remit-to notifications)"
last_revised: "2026-06-14"
trigger: "Material pricing change from current partner (rate increase >0.25%), service failure, recourse terms triggered on a customer default, quarterly partner-comparison review"
related: ["[[Factoring]]", "[[Decision Journal]]", "[[Risk Register]]", "[[Financial Performance]]", "[[Insurance and Banking]]", "[[Playbook — AR Follow-up]]"]
sources: ["raw/xfreight-playbook-factoring-partner-switch.md"]
---

# Playbook — Factoring Partner Switch

**When to run.** Triggered by:

- A material pricing change from the current factoring partner (rate increase >0.25%, fee structure change).
- A service failure (slow funding, dispute mishandling, customer relationship damage).
- Recourse terms triggered on a customer default — review whether current partner's terms are sustainable.
- Quarterly partner-comparison review (regardless of trigger).

**Goal.** Move to the new partner with zero gap in funding, full transition of in-flight invoices, and no customer disruption (customers should never know a switch happened).

**Pre-checks.**

1. Pull current month's factored volume ($ and invoice count) from QB.
2. Pull current partner's contract: notice period, termination clauses, recourse window.
3. Confirm the new partner's terms in writing: rate, advance %, recourse window, customer notification method.
4. Confirm the new partner can accept XFreight's top 5 customers (some partners exclude certain credit profiles).
5. Pre-budget the transition cost: dual-running fees during overlap, any termination fees.

---

## Steps

1. **Decision committed (JB sign-off)** — set the target switch date 60+ days out. Notify the current partner in writing per their contract notice period.
2. **Customer notification packet prepared** — single letter from XFreight (NOT from the new factor) saying "remit payments to a new address starting [date]." Audra owns the mailing/email.
3. **NOA (Notice of Assignment) sequence** — coordinate with both partners: current partner stops accepting new invoices at cutoff date; new partner starts. Old NOA released, new NOA filed, in lockstep.
4. **Customer remit-to update** — Audra contacts each customer's AP team directly (call + email) to confirm the new remit-to. Watch for "we already paid old address" during the first 30 days.
5. **In-flight invoice handling** — invoices factored to the OLD partner stay with them until paid; new invoices go to the NEW partner. No mid-invoice reassignment.
6. **30-day post-switch review** — verify all in-flight invoices cleared with the old partner, all new invoices funding with the new, no customer remit-to errors. Close out the old account.

---

**Decision points.**

- **If the current partner's recourse window is mid-flight on a delinquent customer** — wait until that recourse resolves before switching, OR negotiate carve-out terms with the new partner.
- **If a major customer can't be accepted by the new partner** — keep that customer on the old partner, OR factor them with a third partner, OR carry the AR internally.
- **If the switch happens mid-RFP cycle** — pause non-essential customer communications until the remit-to update is in.

**Escalation.**

- JB for sign-off on the switch decision itself.
- Outside counsel to review the new partner's contract before signing.
- First Dakota National Bank (Mike Flint) notified of factoring change — may want to update treasury setup.

**Capture.**

- Append the switch outcome to the run log below (from/to partner, switch date, transition cost, problems encountered).
- Update [[Factoring]] with the new partner as active and the old as historical.
- Add a [[Decision Journal]] entry: why we switched, predicted savings/improvements, actual outcome at the 90-day mark.

---

## Recent Runs *(append-only)*

**2026-06 — Triumph onboarding (in-flight as of June 14, 2026).** Triumph selected as the new factoring partner (over Pathward / OTR / eCapital). Onboarding expected June 16–17, 2026. Required paying off the existing operating loan — funded by $40K owner capital injection ($20K Jeff + $20K JB) plus a trailer refinance to cover the difference. Cash-flow relief expected once onboarded. Full outcome to be captured when the onboarding completes.

## Connections

- [[Factoring]] — four vendors compared; Triumph selected as of June 2026.
- [[Decision Journal]] — "Selected Triumph for invoice factoring" entry (2026-06).
- [[Risk Register]] — "Factoring onboarding (Triumph)" entry tracking onboarding execution.
- [[Playbook — AR Follow-up]] — AR collections playbook; factoring recourse intersects at the 91-day decision point.
- [[Financial Performance]] — cash flow and AR aging context.

## Sources

- `raw/xfreight-playbook-factoring-partner-switch.md`
