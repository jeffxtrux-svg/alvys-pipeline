# XFreight active disputes and open issues (seeded 2026-06-05 from OneDrive)

> Source: `03 - Finance/Insurance/X-Trux Ins/Acrisure/Acrisure Cov 2.docx`,
> `Accrisure conv 1.docx`, `X-Trux Acrisure Reconciliation v3 42826.xlsx`,
> `X-Trux Invoice Check Match copy.xlsx` (Apr 2026 work),
> `03 - Finance/JW Logistics Legal/` folder.

## 1. Acrisure insurance reconciliation dispute — ACTIVE

**The issue:** Acrisure (current insurance broker) and X-Trux's books disagree on what's been paid and what's owed. As of late April 2026, **~$43,739 in credits are in dispute** — Acrisure has them in their books, X-Trux has them in theirs, neither party has applied them.

### Status timeline

- **Apr 24, 2026** — Acrisure issued a breakdown of what they claim X-Trux owes
- **Apr 26, 2026** — X-Trux check register reconciled through this date
- **Apr 27, 2026** — Two conversation/analysis docs created: `Accrisure conv 1.docx` (notes about the $43,739 credits + that "both your books and theirs show these as open" — strong negotiating position) and `Acrisure Cov 2.docx` (notes about commission Acrisure earns annually based on policy size — questioning whether the dispute is being slow-walked deliberately)
- **Apr 28-29, 2026** — Reconciliation v3 spreadsheet built combining 8 bill.com payment screenshots with the check register
- Several "Accrisure 42826" files capture per-month invoice matching

### Source files

- `03 - Finance/Insurance/X-Trux Ins/Acrisure/Acrisure Cov 2.docx` — Cov letter / argument letter
- `03 - Finance/Insurance/X-Trux Ins/Acrisure/Accrisure conv 1.docx` — Analysis notes
- `03 - Finance/Insurance/X-Trux Ins/Acrisure/X-Trux Acrisure Reconciliation v3 42826.xlsx` — the master reconciliation
- `03 - Finance/Insurance/X-Trux Ins/Acrisure/X-Trux Invoice Check Match copy.xlsx` — invoice-to-check matching
- `03 - Finance/Insurance/X-Trux Ins/Acrisure/Accrisure 42826.xlsx` + copy — monthly Truk-Way bills 2025 (1/25/2025 #6178 $3,270 through 8/25/2025)
- `Bills Inbox/Invoice33980.pdf` — current Acrisure invoice (account X-TRINC-01), received 2026-06-01

### What to watch

- The $43,739 credit dispute is unresolved as of seed date
- This affects X-Trux's QB liability balance + the AR aging on page-11 of the brief (Acrisure shows as a vendor, not a customer, but their unapplied credits muddy the AP side)
- If credits are eventually applied, X-Trux's effective insurance cost drops

## 2. JW Logistics — disputed relationship + exclusion policy

**The issue:** JW Logistics is excluded from every XFreight executive report (see `xfreight-jw-logistics-exclusion.md` for the policy detail). The folder `03 - Finance/JW Logistics Legal/` contains:

- `Summary-Invoice-S1000067.pdf` (X-Linx invoice S1000067 to JWL, dated 12/5/2024)
- Likely other invoices and dispute documentation

The folder `08 - Sales/Customers/JW Logistics/JW Rate Questioning/` contains email threads about flat-rate moves and rate disputes:

- `BIS and MOT moved to Flat Rate January 22, 2024.eml` — internal discussion with Gary and Kyle about route/volume info, transitioning to per-100-weight rates

NDAs are being negotiated in 2025-2026:

- `Re- JWL- NDA- X Freight.eml` (Aug 26, 2025)
- `Re- JWL- NDA- X Freight 2.eml` (Sep 2, 2025)

Both reference "Section 6-a" about partner relationships and existing contracts. So XFreight is balancing the JWL relationship (still a carrier under the 2023 Master Broker-Carrier Agreement) with the reporting exclusion + dispute work.

### Why the exclusion exists

Not documented in code comments. Likely connected to:
- Rate disputes ("JW Rate Questioning" folder)
- Late or short payments that distorted AR aging
- Legal correspondence ("JW Logistics Legal" folder)

The hardened `_is_ar_excluded()` name matcher in `src/scorecard_email.py` keeps JWL out of all reports even if QB or Alvys data spell the name slightly differently.

## 3. Billion Auto contract — EXPIRES THIS MONTH (06/01/2026)

The `Billion Auto.docx` rate agreement was for **06/01/2025 – 06/01/2026**. As of the seed date (June 5, 2026) — **the agreement has just expired**. Either:

- A renewal has been signed (not yet captured in OneDrive)
- A renegotiation is in progress
- The relationship is being wound down
- The expiration was missed

This is daily-revenue freight (~$2,150/day across two lanes) — $47K/month if maintained. **Action item: confirm Billion Auto status.**

## 4. AGCO bid — DECISION PENDING

The AGCO RFP is in final stages. Round 2 closed Dec 22, 2025, carrier selection during that same week, rates effective Feb 1, 2026. As of June 2026, awards should have already been announced. **Need to check current status** — XFreight may or may not have won, and what lanes if so.

## 5. X-Linx brokerage revenue collapse

Per `xfreight-historical-performance.md`, X-Linx revenue has fallen from ~$185K/month (Aug-Dec 2024) to ~$60K/month (2026 YTD). Margin % also down (19% → 12%). This is a quiet but material issue worth investigating:

- Lost a major customer?
- Brokerage market conditions?
- Capacity constraints (fewer trucks to broker against)?
- JWL exclusion impact (if X-Linx was brokering for JWL, that volume is gone)?

## 6. Fleet shrinkage

23.4 trucks (Aug-Dec 2024 avg) → 18.4 trucks (2026 YTD avg) = -21% fleet reduction over 18 months. Per the OO program doc, X-Trux is recruiting actively. The "Future 1-20" slots in `XFreight Goals.xlsx` show 20 reserved truck slots — recruiting targets.

The "Active Trucks · MTD" tile on the page-1 brief shows ~15 — even lower than the 2026 YTD average of 18.4. Either some trucks dropped off, or the actuals worksheet is leading vs. the brief is current.

## 7. SBA 504 capital plan (pro forma)

`03 - Finance/Financials/Profit and Loss/Performa/X-Freight Performa V2.xlsx` mentions:
- Cash injection required: $230K
- SBA 504 required cash injection: $180K

This is a financial plan tied to capital raising, not currently funded. Status unclear from artifacts surfaced. **If SBA 504 is being pursued, it shapes the next 12-month financial strategy.**
