---
title: Factoring
type: concept
tags: [finance, cash-flow, factoring, triumph, ar]
sources: ["raw/xfreight-finance-factoring.md", "raw/triumph-factoring-notes-2026-06-19.md"]
related: ["[[Financial Performance]]", "[[AGCO RFP]]", "[[Brokerage X-Linx]]", "[[QuickBooks Integration]]", "[[Insurance and Banking]]", "[[Rate-Per-Mile Goal]]", "[[Risk Register]]"]
---

# Factoring

XFreight selected **Triumph Business Capital** for invoice factoring in June 2026. Go-live: **Monday June 23, 2026**. Rate: **1.25% flat** on both the carrier (X-Trux) and brokerage (X-Linx) sides. Factoring converts unpaid invoices into cash within 24–48 hours, eliminating the 30–90 day AR collection lag that was overdrawn the bank despite positive net income.

## Key Terms — Triumph (confirmed June 2026)

| Item | Detail |
|---|---|
| **Rate** | 1.25% flat (carrier + brokerage) |
| **Volume to reach 1%** | Revenue must roughly double (~$880K/month minimum) |
| **Advance timing** | 24–48 hours after submission |
| **Advance rate** | 90–97% of invoice face value (confirm exact % on term sheet) |
| **Go-live** | Monday, June 23, 2026 |
| **Buyout** | Triumph bought out the existing First Dakota operating loan position (required to take first position on AR) |
| **Primary contact** | Chase Griffith — cgriffith@triumphpay.com, 214-513-9624 |
| **Rate negotiated by** | Scott (Triumph) — reduced from trying to get 1% flat (denied, volume too low) to 1.25% |

## How Factoring Works Day-to-Day

1. Deliver load → get signed BOL + POD
2. Submit invoice + documents via Alvys (no manual portal upload — see Alvys workflow below)
3. Triumph advances 90–97% of invoice face value within 24–48 hours
4. Triumph sends **Notice of Assignment (NOA)** to each customer/broker — they pay Triumph directly, not XFreight
5. When customer pays Triumph, the reserve releases to XFreight (minus the 1.25% fee)

**Same-day submission discipline matters most.** A load delivered Monday that isn't submitted until Friday funds Monday — 5 days of float lost for nothing. Audra's workflow: POD received → invoice in Alvys → factored same day.

## Alvys Native Integration

Alvys has a built-in Triumph integration — no manual invoice upload to a portal.

1. Load delivered, POD captured in Alvys
2. Open invoice in Alvys → select **"Factor"**
3. Alvys transmits the invoice electronically to Triumph
4. Load status in Alvys shows **"Factored"** — keeps AR aging clean
5. First-time brokers/customers require a Triumph credit check before advance is issued

**Day-one Alvys setup:**
- Enter Triumph account/routing (where advance deposits land)
- Set Triumph as the default factor for X-Trux and/or X-Linx
- Confirm which customers are NOA-approved

## Things That Can Block a Factor

- **Non-factorable customers:** Some shippers won't accept NOA (rare — typically private shippers or government). Know these before Audra submits.
- **Disputed / short-pay loads:** Triumph holds reserve until resolved.
- **First-time broker credit check:** Triumph must approve a broker before factoring that broker's loads. Build time for this on new customer relationships.

## Per-Mile Financial Impact (X-Trux own-fleet)

The 1.25% fee scales directly with RPM — it is a straight percentage of revenue per mile:

| RPM | Fee/mile (1.25%) | Net RPM after fee |
|-----|-----------------|-------------------|
| $2.73 (current Jun 2026) | $0.034 | $2.696 |
| $2.92 (current goal) | $0.037 | $2.883 |
| **$2.96 (break-even to net $2.92)** | $0.037 | **$2.923** |

**Implication for the RPM goal:** To net $2.92/mile after factoring, X-Trux needs to bill at **~$2.96/mile gross**. The rate goal should be understood as $2.92 net of factoring fees. See [[Rate-Per-Mile Goal]].

## Monthly Cost at Current Revenue Run Rate

- June 2026 MTD (19 days) = $277,187 → full-month pace ≈ **$438,000/month**
- 1.25% of $438K = **~$5,475/month** in factoring fees (X-Trux + X-Linx combined)

Volume to reach 1% rate: roughly doubling to ~$880K/month revenue.

## X-Linx Brokerage — Different Economics

The 1.25% fee on brokerage hits gross revenue, not the margin spread. At a typical 12–18% brokerage gross margin, the factoring fee represents roughly **7–10% of the actual brokerage margin** — more impactful per-dollar of profit than on the carrier side. Brokerage load pricing should reflect this cost.

## Comparison: Factoring vs. First Dakota Operating LOC

**First Dakota National Bank:** officer Mike Flint (mflint@firstdakota.com, 605-333-8210). See [[Insurance and Banking]].

| | First Dakota LOC | Triumph Factoring |
|---|---|---|
| Cash timing | Borrow to bridge → still wait for AR | Triumph advances 24–48h |
| Collections | XFreight chases its own AR | Triumph handles collections |
| Balance sheet | Debt on books | Off-balance-sheet |
| Broker credit checking | None | Triumph vets each broker |
| Covenant/LOC risk | Yes (was near max Apr 2026) | None |
| Monthly cost (rough est.) | Rate × balance × (days/365) | 1.25% of revenue factored |

**Pure cost example:** At 8% APR carrying $300K outstanding for 45 days ≈ $2,959/month vs factoring at ~$5,475/month. LOC is cheaper on paper by ~$2,500/month.

**Why factoring won:** The LOC was near-max and the bank was ~$26K overdrawn in April 2026 despite positive net income — a collections-lag structural problem, not a profitability problem. A LOC lets you borrow more while the problem continues; factoring eliminates the root cause by delivering cash in 24–48h and removing the collections burden entirely.

*To complete the exact comparison: need First Dakota current rate and outstanding balance.*

## Impact on the Data Pipeline and Reports

- **`AR_Open` and `AR_60Plus` KPIs** in the daily brief and KPI trend will fall materially as factoring flows — the 60+ bucket should approach zero over 60–90 days
- **QuickBooks AR aging** will look different — factored invoices need to be flagged "sold to factor" vs. "direct billed" so aging is interpreted correctly
- **Alvys→QB AR reconciliation** (pages 12–13 of the brief) reflects factoring timing
- **Future Triumph API connector** (discuss June 23): if Triumph exposes an API, we can pull advance status, reserve balance, and disbursements into the pipeline and reconcile against QB AR — same pattern as the Ramp bills vs QB gap. See [[Data Pipeline Architecture]].

## Vendor Comparison (evaluated late 2025–June 2026)

| Vendor | Contact | Rate | Notes |
|---|---|---|---|
| **Triumph** ✓ **selected** | Chase Griffith (cgriffith@triumphpay.com, 214-513-9624) | **1.25%** | Selected June 2026; Alvys native integration |
| Pathward | Sherri Myers (smyers@pathward.com, 586-709-1360) | ~1.0% | Full advance, no reserve, free ACH, $5 wire |
| OTR Solutions | Sawyer Folks (sawyer.folks@otrsolutions.com, 470-900-3505) | ~1.0% | Dedicated reps, online portal, no setup fee |
| eCapital | Alex Sanchez (Alex.Sanchez@ecapital.com, 760-253-6325) | 1.5% + Quick Pay 2.5% | 12-mo contract, 60-day notice; targets brokerage/carrier Quick Pay |

## Connections

- [[Rate-Per-Mile Goal]] — factoring adds ~$0.034/mi cost; goal should be understood as $2.92 net, bill at $2.96 gross
- [[Brokerage X-Linx]] — 1.25% on brokerage gross = 7–10% of actual brokerage margin; price loads accordingly
- [[Financial Performance]] — cash-flow context; LOC was near-max Apr 2026
- [[Insurance and Banking]] — First Dakota LOC comparison; Mike Flint is the banking contact
- [[AGCO RFP]] — 60-day payment terms were the original factoring trigger
- [[QuickBooks Integration]] — AR aging buckets change character with factoring
- [[Data Pipeline Architecture]] — Triumph API connector planned; same pattern as Ramp reconciliation
- [[Risk Register]] — LOC-near-max / working-capital risk should update to reflect factoring going live

## Sources

- `raw/xfreight-finance-factoring.md`
- `raw/triumph-factoring-notes-2026-06-19.md`
