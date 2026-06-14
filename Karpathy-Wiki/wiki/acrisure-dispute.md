---
title: Acrisure Dispute
type: concept
tags: [insurance, finance, dispute, acrisure]
sources: ["raw/xfreight-active-disputes-and-issues.md", "raw/xfreight-acrisure-dispute-detail.md", "raw/xfreight-insurance-and-banking.md"]
related: ["[[Key People]]", "[[Financial Performance]]", "[[SBA 504 Financing]]", "[[XFreight Entities]]"]
---

# Acrisure Dispute

An active billing reconciliation dispute between X-Trux and Acrisure (current insurance broker), as of April/May 2026. Acrisure claims ~$95,461 owed; Jeff Hannahs's analysis puts the likely liability at ~$31,266. Unresolved as of seed date (June 5, 2026).

## Summary

Acrisure issued a breakdown claiming ~$95K in unpaid premiums on April 24, 2026. Jeff's reconciliation (built from the X-Trux check register + 8 bill.com screenshots) shows $43,739 in unapplied credits sitting on both parties' books — using those credits as the opening negotiation move reduces the actual liability to ~$31K. Three invoices Acrisure can't produce clean copies of are a further $30K that can potentially be challenged to zero.

## Key Ideas

- **$43,739 unapplied credits** are on both Acrisure's books and X-Trux's books — XFreight's primary leverage.
- **Most likely settlement: ~$31,000** (Jeff's middle scenario).
- **Floor: ~$13,000** (if all four "Found unpaid" also challenged — unlikely).
- **Ceiling: ~$66,000** (if all challenged items are valid).
- The $43,739 credit issue opens the negotiation in XFreight's favor, per Jeff's script.

## Insurance Background

- **Current broker:** Acrisure Midwest Trust (replaced Fischer Rounds / Transportation Ins Svcs-Pierre).
- **Current carrier:** Great West Casualty (NAIC 11371) — auto, cargo, GL. Also the underwriter for driver MVR/PSP approvals.
- **Workers' comp carrier:** Technology Insurance Company (NAIC 247643208).
- **Monthly X-Trux payments:** ~$2,240/month (per check register).
- 2026 liability-insurance rate hike absorbed into the `RPM_GOAL_OVERHEAD_PIN` (bumped $0.92→$0.98). See [[Rate-Per-Mile Goal]].

## Item-by-Item Breakdown

| Item | Amount | Category |
|---|---|---|
| X-TRINC: Four "Found unpaid" invoices (16574, 23111, 9954, 15234) | $61,768.70 | Likely valid — fell through during TIS→Acrisure transition |
| Less unapplied credits | ($43,739.00) | **XFreight's leverage — on both books** |
| **X-TRINC subtotal** | **$18,029.70** | |
| TRUKLEA: WC Audit (Inv 29033) | $11,024.00 | Pay it — based on verified payroll |
| TRUKLEA: Current installment (Inv 24192, March 2026) | $2,225.84 | Pay it — routine |
| X-LIINC: Overpayment credit | ($14.00) | XFreight credit |
| **Most likely actual liability** | **~$31,266** | |

"Could not find" stack (challenge these — ~$30,639):
- Multiple invoices Acrisure references but cannot produce clean copies of, including Inv 27433 "Corrected".

## Negotiating Scenarios

| Scenario | Amount | Probability |
|---|---|---|
| **Floor** | ~$13,000 | Low — requires finding payment evidence for the four "Found unpaid" |
| **Middle** | **~$31,000** | Jeff's estimate — credits applied + three "could not find" challenged |
| **Ceiling** | ~$66,000 | Worst case — everything valid including the challenged invoices |

## Negotiation Script (per Jeff's April 27, 2026 email)

1. Open with the $43,739 unapplied credits — force Acrisure to acknowledge they're on both books.
2. Once credits acknowledged, X-TRINC conversation shifts from $61K to $18K.
3. Challenge each "could not find" invoice — demand clean copies; if Acrisure can't produce them, they go to zero.
4. Pay the WC audit + current installment without argument (audit is verified payroll; installment is routine).
5. Result: $95K ask → ~$31K settlement.

## Why This Matters for the Pipeline

- **QB AP totals:** Acrisure appears as a vendor; disputed amount affects liability balance.
- **Cash flow:** $31K vs $95K spread is material, especially with the [[SBA 504 Financing]] $230K down payment approaching.
- **RPM cost-out:** If dispute resolves favorably, effective insurance cost is lower than the current overhead pin.
- **2026 Truk-Way** WC audit (Inv 29033 = $11,024) is part of this — Truk-Way is the employer of record for W-2 staff.

## Status

**Renewal — RESOLVED: went through May 1, 2026** (Jeff, 2026-06-13), carrying a ~$0.08–0.10/mi premium increase now figured into the cost-out. See [[Rate-Per-Mile Goal]] and [[Risk Register]]. A different broker/carrier may be evaluated before the next renewal.

**Billing reconciliation (~$95K claim) — still open** as of this update. The renewal proceeding does not by itself settle the back-billing dispute; Jeff's April 27 analysis (most-likely ~$31,266) stands as the negotiating position.

Track: Has the $43,739 been applied? What was the final billing settlement?

## Contacts

- **Jami Hewitt** — Senior Truck Account Manager, Acrisure (jhewitt@acrisure.com). Primary daily contact; also handles driver MVR approvals.
- **Kurt Swanson** — Truck Account Manager (kswanson@acrisure.com). Handles renewals.
- **Jeff Hannahs** — XFreight negotiator. JB Sweere in CC on strategic decisions.

## Key Files

- `03 - Finance/Insurance/X-Trux Ins/Acrisure/Accrisure conv 1.docx` — analysis notes.
- `03 - Finance/Insurance/X-Trux Ins/Acrisure/Acrisure Cov 2.docx` — negotiation letter.
- `03 - Finance/Insurance/X-Trux Ins/Acrisure/X-Trux Acrisure Reconciliation v3 42826.xlsx` — master reconciliation.
- `Bills Inbox/Invoice33980.pdf` — current Acrisure invoice (account X-TRINC-01, received 2026-06-01).

## Connections

- [[Key People]] — Jeff, JB, Jami Hewitt, Kurt Swanson.
- [[Insurance and Banking]] — full insurance program context: carriers, historical broker, banking, entity IDs.
- [[Financial Performance]] — insurance cost affects net margin.
- [[Rate-Per-Mile Goal]] — overhead pin absorbs insurance hike.
- [[SBA 504 Financing]] — $43,739 credit (if applied) directly improves cash position for down payment.
- [[Truk-Way Leasing]] — WC audit (Inv 29033) covers Truk-Way payroll.
- [[Active Disputes and Open Issues]] — this dispute is item 1 on the open watch list.

## Sources

- `raw/xfreight-active-disputes-and-issues.md` — summary.
- `raw/xfreight-acrisure-dispute-detail.md` — detailed negotiation analysis.
- `raw/xfreight-insurance-and-banking.md` — broker + carrier background.
