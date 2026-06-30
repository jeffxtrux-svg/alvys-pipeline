---
title: Playbook — Factoring Partner Switch
type: playbook
tags: [playbook, finance, factoring, cash-flow, ar]
status: active
owner: JB Sweere
last_revised: "2026-06-14"
trigger: "Material pricing change from current factoring partner; service failure; recourse triggered on customer default; quarterly partner-comparison review"
sources: ["raw/xfreight-playbook-factoring-partner-switch.md"]
related: ["[[Factoring]]", "[[Financial Performance]]", "[[Insurance and Banking]]", "[[Decision Journal]]", "[[Risk Register]]", "[[Contact Directory]]"]
---

# Playbook — Factoring Partner Switch

Change factoring providers without breaking cash flow. Customers should never know we switched.

## Trigger — When to Run

- Material pricing change from the current factoring partner (rate increase >0.25%, fee structure change).
- Service failure — slow funding, dispute mishandling, or customer relationship damage.
- Recourse terms triggered on a customer default — review whether current terms are sustainable.
- Quarterly partner-comparison review (regardless of trigger).

## Goal

Move to the new partner with zero gap in funding, full transition of in-flight invoices, and no customer disruption.

## Pre-Checks

1. Pull current month's factored volume ($ and invoice count) from QB.
2. Pull the current partner's contract: notice period, termination clauses, recourse window.
3. Confirm the new partner's terms in writing: rate, advance %, recourse window, customer notification method.
4. Confirm the new partner can accept our top 5 customers — some factors exclude certain credit profiles.
5. Pre-budget the transition cost: dual-running fees during overlap, any termination fees.

## Steps

1. **Decision committed (JB sign-off)** — set the target switch date 60+ days out. Notify the current partner in writing per their contract notice period.
2. **Customer notification packet prepared** — single letter from XFreight (NOT from the new factor) saying "remit payments to a new address starting [date]." Audra owns the mailing or email.
3. **NOA (Notice of Assignment) sequence** — coordinate with both partners: current partner stops accepting new invoices at cutoff date; new partner starts. Old NOA released, new NOA filed, in lockstep.
4. **Customer remit-to update** — Audra contacts each customer's AP team directly (call + email) to confirm the new remit-to. Watch for "we already paid old address" in the first 30 days.
5. **In-flight invoice handling** — invoices factored to the old partner stay with them until paid; new invoices go to the new partner. No mid-invoice reassignment.
6. **30-day post-switch review** — verify all in-flight invoices cleared with the old partner, all new invoices funding with the new, no customer remit-to errors. Close out the old account.

## Decision Points

- **If the current partner's recourse window is mid-flight on a delinquent customer** — wait until that recourse resolves before switching, OR negotiate a carve-out with the new partner.
- **If a major customer can't be accepted by the new partner** — keep that customer on the old partner, factor them with a third partner, or carry the AR ourselves.
- **If the switch happens mid-RFP cycle** — pause non-essential customer communications until the remit-to update is in.

## Escalation

- **JB** for sign-off on the switch decision itself.
- **Outside counsel** to review the new partner's contract before signing.
- **Banking partner (First Dakota NB / Mike Flint)** notified of factoring change — may need to update treasury setup.

## Capture

- Append the switch outcome to this playbook's run log (from/to partner, switch date, transition cost, problems encountered).
- Update [[Factoring]] with the new partner as active and the old as historical.
- Add a [[Decision Journal]] entry: why we switched, predicted savings/improvements, actual outcome at the 90-day mark.

## Connections

- [[Factoring]] — vendor comparison table and current partner detail.
- [[Financial Performance]] — cash-flow impact of factoring rate and advance %.
- [[Contact Directory]] — vendor contacts: Pathward (Sherri Myers), Triumph (Chase Griffith), OTR (Sawyer Folks), eCapital (Alex Sanchez).
- [[Insurance and Banking]] — First Dakota NB (Mike Flint) notification on partner change.
- [[Decision Journal]] — switch rationale and 90-day post-mortem belong here.

## Sources

- `raw/xfreight-playbook-factoring-partner-switch.md` — seed 2026-06-14.

---

## Recent Runs

*(append-only log — never overwrite or reorder)*

- **2026-06 — Triumph engagement initiated.** Selected Triumph over Pathward / OTR / eCapital. Onboarding required clearing the existing operating loan via a $40K owner capital injection (Jeff + JB, $20K each) plus a trailer refinance.
- **2026-06-23 — Live (X-Trux flows; X-Linx broke at go-live).** X-Trux asset-side carrier settlements flow correctly. X-Linx brokerage broke — Alvys was not passing carrier payables to Triumph alongside AR invoices; Triumph requires both simultaneously. 144 invoices from the initial buyout unrecorded in both Alvys and QBO.
- **2026-06-26 — Alvys integration meeting.** Alvys owns the fix entirely; no custom build from XFreight. Deliverables: sync 144 invoices to QBO week of 6/30; QBO third-party accounting setup week of 6/30 or following; Triumph Audit feature turned off for XFreight; Andreas (Alvys head engineer) contacts Jeff re: sandbox access 6/30. Target architecture: Triumph → Alvys (two-way) → QBO. **Watch:** confirm deliverables ~week of 7/7; escalate to Andreas if Alvys slips. See [[Factoring]], [[Decision Journal]].
