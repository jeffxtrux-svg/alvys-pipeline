# XFreight owner-operator program (seeded 2026-06-05 from OneDrive)

> Source: `XFreight - Claude Working Files/05 - Recruiting & OO/XTRUX Owner Operator.docx`
> (recruiting one-pager, last modified 2026-04-15).

## Identity

- **X-TRUX, Inc.** — DOT #841776, MC #375851
- Asset-based truckload carrier
- All 48 contiguous states
- Modern fleet of newer trucks + 53' dry van trailers
- DOT inspections that **exceed** federal DOT standards
- 24+ years of refined owner-operator contracts (since 1999)

## Lanes & operations

- Primarily dry van freight throughout the lower 48
- **Heavy delivery presence in:** MA, CT, PA, NC, SC, TN, TX, OH, IL, IA, NE, MN, SD, WA, UT, NV, MO, KS
- **No forced dispatch** — driver chooses general operating area
- OTR drivers run 2-3 weeks out at a time; 34-hour restarts at home when route allows

## Driver pay rates

| Mile type | Recent reference rate (PC Miler Practical) |
|---|---|
| **Loaded miles** | **~$1.89/mile** (varies weekly) |
| **Empty miles** | **~$1.89/mile** (varies weekly — same as loaded) |

### Weekly rate revision — every Wednesday

**Both loaded and empty per-mile rates change every week on Wednesday**, along with the fuel surcharge. The $1.89/mi figure above is a recent reference point, NOT a fixed published rate. The current week's rate is whatever was set on the most recent Wednesday revision.

Implications:

- **Driver settlements** reflect the rate that was in effect for the loads' delivery week, not a single annual rate.
- The owner-op recruiting one-pager publishes a representative rate but recruits should understand it floats weekly.
- The **rate-per-mile cost-out** in the daily brief (`compute_rpm_goal`, `RPM_GOAL_PAY_WINDOW_DAYS = 10`) deliberately uses a **10-day trailing window** specifically because the per-mile rate moves weekly — a 10-day window captures the current week + most of the prior week and blends to a stable read. A longer window would drag in stale rates; a shorter one wouldn't have enough settled loads.
- The weekly Wednesday revision **aligns with the settlement-week boundary** (Wed 3pm CT → following Wed 2:59pm CT). New rate effective from the start of the settlement week.

### Why same rate loaded + empty

Loaded and empty paid at the same per-mile rate is unusual industry-wide (many carriers pay less on empty). It's deliberate at XFreight — simplifies math for drivers, removes incentive to game empty miles, and the deadhead % (~7-8%) is small enough that the cost difference is manageable. The empty miles still get absorbed into the rate-per-mile goal so customers ultimately cover it via the loaded-mile rate.

### Additional pay (typically stable, not tied to weekly revision)

- **Extra stops:** $40/stop (one pickup + one delivery included standard)
- **Detention:** $30/hour after first 2 hours
- **Layover:** $200

## Settlement deductions

Standard deductions from each driver settlement:

- Fuel + quarterly fuel tax (IFTA)
- Insurance (driver uses X-TRUX coverage OR provides their own)
- Truck payment if applicable
- Optional escrow (personal maintenance + tax fund — driver's choice)
- **Licensing:** $200/month × 12 covers apportioned plates + 2290 filing

### Insurance estimates if driver provides own

- Bobtail + physical damage: ~$250-300/week depending on truck value
- Example: $125K truck ~$730/month
- New truck ~$1,200/month

## Truck requirements

- Must be **no older than 5 years**
- Must pass DOT inspection prior to contracting
- X-TRUX covers **all 4 quarterly inspections** (equivalent to the annual DOT standard)

## Unique benefits

- **Pre-pass + tolls covered** by X-TRUX
- **Samsara ELD + forward-facing camera** provided at no cost. **NO driver-facing camera** (deliberate; differentiator).
- **Comdata Fuel Card** with applicable fuel discounts
- No trailer rental fees
- **Trailers inspected every 120 days** (matches the 120-day company DOT policy on page 6 of the executive brief)

## Recruiting flow

- Recruiting docs live under `05 - Recruiting & OO/` in OneDrive
- The XTRUX Owner Operator.docx is the one-page summary handed to prospects
- The XFreight Presentation.pdf (under `05 - Recruiting & OO/`) is the sales/customer-facing deck

## Note on cross-references

- Driver settlement worksheets land in `DispatchFiles/Shared Documents/Alvys Settlements/` (e.g. `baSettlmentWorksheek06032026.xlsx`). One per week.
- The current daily equipment roster lives at `DispatchFiles/Shared Documents/equipnow10.xlsx` — used by dispatch to plan loads.
