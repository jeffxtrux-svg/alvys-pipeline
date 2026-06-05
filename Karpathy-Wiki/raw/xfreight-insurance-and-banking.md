# XFreight insurance + banking (seeded 2026-06-05 from OneDrive)

> Source: `XFreight - Claude Working Files/03 - Finance/Insurance/` (Acrisure
> reconciliations, Final Insurancee.xlsx), X-Linx company profile
> (aalinxpacket.pdf, 2023 vintage), insurance ACORD certificates.

## Current insurance broker — Acrisure

- **Acrisure Midwest Trust** — current insurance broker (replaced earlier broker)
- Reconciliation work happens in `03 - Finance/Insurance/X-Trux Ins/Acrisure/` with files like `X-Trux Acrisure Reconciliation v3 42826.xlsx` (April 2026)
- Acrisure breakdown vs X-Trux check register reconciled monthly via bill.com payment screenshots
- Acrisure invoices flow through QuickBooks as `Acrisure Midwest Trust` payee (vendor list confirms)

## Historical broker (pre-Acrisure)

From the X-Linx packet (2023 vintage ACORD certificate):

- **Transportation Ins Svcs-Pierre** (Fischer Rounds) — Pierre, SD
- **Kurt Swanson Jr.** — 800-444-8332 / 605-224-5831 / kswanson@fischerrounds.com
- Switched to Acrisure later

## 2023 insurance carriers (from the ACORD cert in aalinxpacket.pdf)

Note: 2023 vintage — current carriers may have changed. Confirm against the Acrisure reconciliation for live carriers.

| Coverage | Carrier | NAIC | Limit |
|---|---|---|---|
| Auto liability (X-Linx) | **Great West Casualty** | 11371 | $1,000,000 per occurrence / $2,000,000 aggregate |
| Hired/non-owned auto | Great West Casualty | 11371 | $100,000 |
| General liability | Great West Casualty | 11371 | $1M occurrence / $2M aggregate |
| Cargo (contingent) | Great West Casualty | 11371 | $100,000 ($1,000 per-unit deductible) |
| Workers comp | **Technology Insurance Company** | 247643208 | Statutory |

The 2023 cert was for X-LINX, INC. specifically. X-Trux likely has its own ACORD cert.

## Liability insurance rate hike

Per the rate-per-mile-goal commits earlier this session:

- Liability insurance was previously tracked as a separate $0.07/mi line in the cost-out.
- In 2026 a rate hike pushed insurance higher, and the office overhead pin was bumped from $0.92 to $0.98/mi to absorb the increase. The separate insurance surcharge constant `RPM_GOAL_INSURANCE_SURCHARGE` was zeroed at that point so insurance isn't double-counted.
- See `xfreight-rate-per-mile-goal.md` for details.

## Insurance payments (from Final Insurancee.xlsx, 2025)

- Acrisure Midwest Trust payments appear in X-Trux Payments 2025 register
- Example: 11/20/2025 Bill Payment (Check) Acrisure Midwest Trust -$2,240.31 (Check #5311, scheduled 07/31/2025)
- Monthly cadence

## Banking — First Dakota National Bank

Per the X-Linx packet:

- **First Dakota National Bank**
- 6109 South Old Village Place, Sioux Falls, SD 57108-2104
- Phone: 605-333-8210
- **Bank Officer: Mike Flint**

Likely banks both X-Trux and X-Linx (and possibly Truk-Way). Confirm against current GL or check register.

## Federal IDs

| Entity | Federal Tax ID |
|---|---|
| X-Linx, Inc. | **45-0452444** |
| X-Trux, Inc. | (not captured yet — likely in QB or W-9 files) |
| Truk-Way Leasing | (not captured yet) |

## DOT numbers (for completeness)

| Entity | DOT # | MC # |
|---|---|---|
| X-Trux, Inc. | **841776** | **375851** |
| X-Linx, Inc. | **2224732** | **353490** |

(Both are South Dakota corporations, both incorporated January 19, 1999.)
