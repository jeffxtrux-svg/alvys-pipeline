# XFreight SBA 504 financing — building + business purchase in progress (seeded 2026-06-05 from Outlook)

> **Update (2026-06-13, Jeff): SHELVED — not currently on the table.** Removed from the active risk list. Historical context retained below in case it returns.

> Source: Email thread between Jeff Hannahs ↔ JB Sweere ↔ Mike Flint
> (First Dakota National Bank), Feb 11-19, 2026.

## What's being financed

A combined real-estate-plus-business-purchase transaction with a stated price of **~$3M**.

From Jeff's email (Feb 11, 2026):
> *"The total project... SBA has requirements that allow some seller carry back, but I believe based on a transaction with a purchase price of $3M we're already on the skinny side of..."*

From JB's email (Feb 12, 2026):
> *"term sheet from my 504 partner for the building financing package. Once I receive that I will follow up with you with some additional details, but I made the assumption to assign a..."*

The loan would include "all current tractors, trailers, property, and the business purchase" per Jeff's question to Mike Flint.

## Status (as of Feb 2026)

- **Reviewing cash flows** to confirm sufficient cash flow to support the loan
- **Awaiting term sheet** from JB's 504 partner
- Mike Flint (First Dakota Bank Officer) is the bank-side contact
- Still **evaluating options** — Jeff wrote Feb 19: *"We are still reviewing things at the moment. We have just started looking at the cash flows and are trying to confirm there is enough cash flow..."*

## Cross-reference: the Performa V2 workbook

The pro forma at `03 - Finance/Financials/Profit and Loss/Performa/X-Freight Performa V2.xlsx` lines up with this financing:
- Cash injection required: **$230K**
- SBA 504 required cash injection: **$180K**
- Total project value implied: ~$3M (per the bank conversation)

The Performa is the supporting analysis for the SBA application.

## Structure (typical SBA 504)

SBA 504 loans typically structure as:
- **50%** first mortgage from conventional lender (likely First Dakota, Mike Flint's bank)
- **40%** SBA-backed Certified Development Company (CDC) loan ("504 partner")
- **10%** borrower equity contribution
- Optionally seller carry-back (with SBA caps) within the 10%

A $3M project would imply approximately:
- ~$1.5M First Dakota first mortgage
- ~$1.2M SBA 504 (CDC) loan
- ~$300K borrower equity (which lines up with the $230K cash + $70K of other equity)

## What's being purchased

Per Jeff's email: "all current tractors, trailers, property, and the business purchase"

This sounds like XFreight is **buying out a stakeholder** or **consolidating ownership** — purchasing the real estate (the building XFreight currently operates from), the trucks and trailers (potentially currently leased or held in Truk-Way Leasing LLC), and the business itself.

Possible scenarios:
1. **JB is buying out other shareholders** (more concentrated ownership)
2. **Acquiring Truk-Way Leasing** (folding the trailer/asset leasing entity into the carrier)
3. **Acquiring the building** (currently rented, moving to owned)
4. **Some combination**

The NJ Trailers + NJ Properties LLC entities in the QB chart of accounts (per `connector-quickbooks.md`) may be part of this — those are entities not yet live in the pipeline because their refresh tokens "don't exist yet." A real-estate purchase via NJ Properties would explain why those entities exist in QB but aren't fully wired up.

## Implications for the pipeline

- **NJ Properties + NJ Trailers** entities would come online in QB after closing
- The pipeline already has env var slots for `QB_NJ_TRAILERS_REFRESH_TOKEN` and `QB_NJ_PROPERTIES_REFRESH_TOKEN` — once the entities have OAuth set up, the pipeline picks them up automatically
- The rate-per-mile-goal cost-out would change because lease payments would shift to debt service
- The page-1 entity tiles may need to add the new entities (NJ Properties / NJ Trailers) to the rollup

## Implications for cash flow

- **Down payment ~$230K** in cash needed
- Monthly debt service on $2.7M+ debt at SBA rates is ~$20-25K/month
- Currently $180K/month margin goal — debt service would consume ~10-15% of monthly margin

## Track from here

This is one of the most important strategic decisions in flight. Track:

- When the 504 partner term sheet lands
- Acceptance / decline / counter
- Closing date
- Whether NJ entities go live in QB after closing
- How the operating ratio on the rate-per-mile goal changes post-acquisition

Files to watch: `03 - Finance/Financials/Profit and Loss/Performa/` and any new docs landing in OneDrive related to "SBA 504," "Building," "Property Purchase," or "Acquisition."
