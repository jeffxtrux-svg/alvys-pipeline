---
title: Decision Journal
type: register
tags: [decisions, finance, operations, decision-support]
sources: ["raw/xfreight-decision-journal.md"]
related: ["[[Risk Register]]", "[[Recent Decisions 2026-06-05]]", "[[Rate-Per-Mile Goal]]", "[[Brokerage X-Linx]]", "[[Owner-Operator Program]]", "[[AGCO RFP]]", "[[Safety Program]]", "[[Daily Scorecard Email]]"]
last_reviewed: "2026-06-15"
---

# Decision Journal

A running log of XFreight's consequential decisions — each with the **rationale**, the **assumptions** it rests on, and the **predicted outcome**, so that later we can grade it. Most businesses never write down *why* they made a call, so they can't tell good judgment from luck. Over time this page answers: which kinds of bets actually pay?

> **How this page works.** When a meaningful decision is made, append it to `raw/xfreight-decision-journal.md` using `templates/decision.md`; the librarian compiles it here. Leave the **Actual outcome** blank at first and fill it in once known — then set `outcome` to confirmed / mixed / wrong and note the lesson. This is distinct from [[Recent Decisions 2026-06-05]], which logs *pipeline/code* changes; this page is for **business and measurement decisions**. **Seeded 2026-06-13 — assumptions and predicted outcomes need Jeff's review.**

## At a glance

| Date | Decision | Predicted outcome | Status |
|------|----------|-------------------|:------:|
| 2026-06-14 | Role-focused brief delivery | Faster accountability per area | Pending |
| 2026-06-13 | Acrisure billing settled at $18K (paid) | $95K ask → $18K, near floor | **Confirmed** |
| 2026-06 | Billion Auto renewed (lanes + FSC) | Secures ~$47K/mo + fuel protection | **Confirmed** |
| 2026-06 | Factoring: selected Triumph | Cash-flow relief once onboarded | Pending — ~6/16–17 |
| 2026-06-13 | X-Trux P&L hold-out at ≥74% margin | P&L matches Power BI, reflects own-fleet | Pending |
| 2026-06-13 | Deadhead / RPM = own-fleet only | 5.448% true own-fleet deadhead | Pending |
| 2026-06-12 | Retire SambaSafety API → CSV-drop | Compliance/CSA data keeps flowing | Pending — review ~7/12 |
| 2026-06-13 | Next oil change as a 25k estimate | "Close enough" until real data | Pending |
| Standing | Dispatch date locks the pay rate | Consistent settlement, no disputes | Confirmed |
| 2026-05-01 | Renew with Acrisure (+$0.08–0.10/mi) | Increase absorbed into costing | Confirmed |
| 2026-01 | Bid the AGCO 2026 RFP | (win the lane) | **Wrong** — not awarded |

---

## 2026-06-13 — Acrisure billing dispute settled at $18,000 (paid)
**Decision.** Settle the Acrisure back-billing reconciliation. **Outcome.** Negotiated from the ~$95K ask down to **$18,000, paid and resolved** — below Jeff's ~$31K mid-estimate and near his ~$13K floor. Graded **confirmed / well-executed**: leading with the $43,739 unapplied credits and challenging the "could not find" invoices worked. **Lesson.** The credits-first negotiation script delivered ~$77K of savings vs the ask. See [[Acrisure Dispute]], [[Risk Register]].

## 2026-06 — Billion Auto contract renewed (lanes maintained + FSC added)
**Decision.** Renew the Billion Auto dedicated agreement. **Outcome.** Renewed — both the **Rapid City** and **Mason City** dedicated lanes maintained, and a **fuel surcharge added for protection this year**. Graded **confirmed**. **Why it matters.** Secures ~$47K/mo of daily-volume revenue (the portfolio's most immediate revenue risk) and the FSC hedges fuel-price exposure going forward. See [[Billion Auto]], [[Customer Portfolio]].

## 2026-06 — Selected Triumph for invoice factoring
**Decision.** Choose **Triumph** for factoring (over Pathward / OTR / eCapital); onboarding expected ~June 16–17, 2026. **Rationale.** Relieve cash flow on slow-pay AR. **The catch.** Onboarding required clearing the existing operating loan — funded by a **$40K owner capital injection ($20K Jeff + $20K JB)** plus a **trailer refinance** to cover the difference. **Predicted outcome.** Shorter AR-to-cash cycle, easier cash flow. **Actual.** _Pending — onboarding ~6/16–17; then watch AR aging shorten._ See [[Factoring]], [[Financial Performance]], [[Risk Register]].

## 2026-06-13 — X-Trux P&L hold-out at ≥74% Corrected Margin
**Decision.** Exclude X-Trux loads that are status "Open" OR have Corrected Margin % = (Revenue − Driver Rate)/Revenue ≥ 74% from the entity P&L. **Rationale.** Those are office loads brokered to outside carriers with a tiny placeholder driver rate; counting them inflates own-fleet P&L. **Assumption.** ≥74% margin reliably identifies brokered/under-costed loads. **Predicted outcome.** Brief P&L matches Power BI to the penny and reflects true own-fleet economics. **Actual.** _TBD — watch for genuine high-margin own-fleet loads wrongly held out._ See [[Brokerage X-Linx]], [[Rate-Per-Mile Goal]].

## 2026-06-13 — Deadhead / RPM scoped to own-fleet only
**Decision.** Deadhead %, asset RPM, and mileage tiles count X-Trux own-fleet loads only (exclude X-Linx AND brokered X-Trux). **Rationale.** Deadhead is empty miles *your own trucks* drive; carrier-driven loads aren't your deadhead. **Predicted outcome.** 5.448% true own-fleet deadhead (vs 4.90% with brokered loads in). **Actual.** _TBD._ See [[Rate-Per-Mile Goal]].

## 2026-06-12 — Retire SambaSafety API, switch to CSV-drop
**Decision.** After the API token expired 2026-06-02, retire API mode and read the CSVs Power Automate drops into OneDrive. **Rationale.** API access lapsed; CSV covers driver compliance + CSA needs without renewal cost. **Assumption.** The Power Automate CSV drop stays reliable. **Predicted outcome.** Driver-compliance and CSA data keep flowing. **Actual.** _TBD — review ~2026-07-12._ Paired risk: "SambaSafety CSV fragility" in [[Risk Register]]. See [[Safety Program]], [[Data Pipeline Architecture]].

## 2026-06-13 — Next oil change shown as a 25k estimate
**Decision.** Show estimated next-oil-due mileage (current odometer → next 25k mark, labeled "est") rather than wait for real odometer-at-service capture. **Rationale.** Deliver visible value now; the page auto-flips to a real value once Alvys logs the odometer at each oil change. **Predicted outcome.** The estimate is close enough to be useful in the interim. **Actual.** _TBD when real oil-odometer data exists._ See [[Daily Scorecard Email]].

## Standing rule — dispatch date locks the per-mile pay rate
**Decision.** Driver per-mile pay rate is revised weekly on Wednesday; a load's dispatch date determines which week's rate applies (Tuesday dispatch → prior rate, Wednesday → new rate). **Rationale.** An unambiguous rule for which rate a load pays, for settlement. **Predicted outcome.** Consistent settlement, no rate disputes. **Actual.** In effect — treated as confirmed. See [[Owner-Operator Program]], [[Rate-Per-Mile Goal]].

## 2026-05-01 — Renewed insurance with Acrisure (+$0.08–0.10/mi)
**Decision.** Renew X-Trux / X-Linx insurance with Acrisure (Great West Casualty underwriter) effective May 1, 2026, accepting a ~$0.08–0.10/mi premium increase. **Rationale.** Keep coverage continuity through the renewal; no better-priced option lined up in time. **Predicted outcome.** The higher premium is absorbed into the cost-out so the rate-per-mile goal stays whole. **Actual.** Renewal completed 5/1/26; the increase is figured into the costing (overhead pin $0.98 — confirm it fully reflects $0.08–0.10/mi; see [[Risk Register]]). **Forward.** Evaluate an alternative broker/carrier before the next renewal — a different option may be needed down the road. Outcome **confirmed** (renewal done, cost absorbed). See [[Insurance and Banking]], [[Acrisure Dispute]], [[Rate-Per-Mile Goal]].

## 2026-06-14 — Role-focused brief delivery (org accountability map)

**Decision.** Restructure brief delivery from a single 13-page Executive brief that everyone receives into role-focused daily briefs aimed at the owner of each area, with Jeff + JB cc'd on everything for governance visibility. The executive brief stays as the consolidated leadership view.

**Distribution plan** (canon also in [[Employee Responsibilities]] and repo-root `CLAUDE.md`):
- **Executive** → Dan, JB, Jeff (existing — already live).
- **Safety & Compliance** → Audra; Jeff, JB cc. (`safety_compliance_email.py` already built; in jeff-only test mode.)
- **Operational / Maintenance** → Jackson, Dan; Jeff, JB cc. (Not yet built.)
- **Accounting / Financial** → Jeff, JB. (Not yet built.)
- **Sales** (weekly Monday) → Jeff; JB cc. (Not yet built.)
- **Recruiting** (weekly Monday) → Jeff; JB cc. (Not yet built.)

**Responsibility assignments** (canonical — must match playbook + risk-register `owner:` fields):
- **Audra** — Safety, Compliance, invoice closeout.
- **Jackson + Dan** — On-time delivery, truck coverage/return loads, drivers ≥2,750 mi/wk average.
- **Jeff + JB** — Accounting/financial, sales, recruiting.

**Rationale.** A single 13-page brief everyone receives gets skimmed — people don't read the parts that aren't theirs and miss the parts that are. Role-specific briefs drive accountability; cc'ing leadership keeps visibility.

**Assumption.** Owners actually engage with their brief instead of filing it. If a role's brief isn't read consistently for 2+ weeks, the format is wrong before more is added on top.

**Predicted outcome.** Sharper accountability per area; faster action cycles on safety, operational, and AR items; less "everyone read it, no one acted" diffusion.

**Actual.** _TBD — review after new briefs land + run for 30 days. Grading signals: are tripped Risk Watch items getting acked/closed faster? Are equipment-inspection backlog items cleared within the 14-day playbook window? Is AR aging dropping or holding?_ See [[Risk Register]], [[Playbook — Equipment Inspection Backlog]].

---

## 2026-01 — AGCO 2026 truckload RFP (closed loop)
**Decision.** Bid the AGCO 2026 truckload RFP. **Outcome.** **Not awarded** (Jan 2026). Graded **wrong** (lost). Lessons for the next cycle are in [[AGCO RFP]] — kept here as an example of a decision with a known result, so the journal shows the full loop. See [[Customer Portfolio]].
