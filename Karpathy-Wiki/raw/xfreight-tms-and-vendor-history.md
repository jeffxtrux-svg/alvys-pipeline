# XFreight TMS + vendor history (seeded 2026-06-05 from Outlook)

> Source: Outlook emails (Alvys onboarding, McLeod evaluation,
> Highway.com broker network onboarding, Dart Advantage carrier packet).

## TMS history

### Alvys (current, since March 2024)

XFreight onboarded onto Alvys in **March 2024**. Onboarding contact: **Reuben Sheyko** (reuben.sheyko@alvys.com).

Initial setup pain points (from the onboarding emails):

- **PC Miler availability** — Jeff asked "When will PC Miler be available?" — XFreight needs PC Miler integrated for accurate mileage on every load (rate calcs, settlement, customer billing)
- **Complex pay structure** — JB explained: *"I have 2 owner operator groups with multiple trucks, we pay the truck, however need a settlement for the driver also. Then we have several owner operators."*

So XFreight runs a **hybrid driver-pay model**:
1. **Owner-operator GROUPS** — A fleet owner (group) owns multiple trucks. XFreight pays the group/truck owner, who then pays each driver. Settlement happens for both layers.
2. **Direct owner-operators** — XFreight pays the OO directly per the OO program rates ($1.89/mi).

Both flows have to be representable in Alvys settlements. This complexity is why Alvys had to be customized for XFreight.

### McLeod Software (evaluated Jan 2025, declined)

JB Sweere had a conversation with McLeod Software's Ryan Elmore (ryan.elmore@mcleodsoftware.com) on Jan 9, 2025. JB's note: *"I was being polite and talked to them today."*

**XFreight evaluated McLeod TMS but stuck with Alvys.** McLeod is a major TMS in trucking (especially asset carriers), but the migration cost wasn't justified given Alvys was already configured for XFreight's hybrid pay structure.

## Carrier-broker onboarding (via Highway.com)

XFreight uses **Highway.com** (highway.com) to onboard with brokers' carrier packets — a centralized identity/compliance service so XFreight doesn't have to fill out the same carrier packet for every broker individually.

Confirmed broker connections (from Highway.com email notifications):

| Broker | Connected | Notes |
|---|---|---|
| **RL Solutions, LLC** | 2024-07-09 | Carrier packet submitted by Jeff |
| **Bridge Logistics, Inc.** | 2024-04-29 | Carrier packet submitted by Jeff |
| **Dart Advantage Logistics** | 2024-01-12 | Carrier packet via assureassist.com (separate platform) |

Many more brokers presumably onboarded via the same Highway.com flow over time — these are just the ones surfaced in this email search.

The Highway.com integration means: when a broker wants to use X-Trux as a carrier, the broker requests the packet through Highway, XFreight clicks accept, and credentials sync.

## Telematics / safety vendors

### Samsara (current)
- ELDs + forward-facing cameras (NO driver-facing cameras — deliberate per OO recruiting)
- Safety events, HOS violations, DVIR defects, safety scores
- Owner-op program comp: "Samsara ELD unit & forward-facing camera — provided at no cost"
- Cost: ~$30-40/truck/month (industry standard)

### SambaSafety (current)
- MVR (Motor Vehicle Records) monitoring
- Driver risk index, license status, expirations
- FMCSA CSA Scorecard CSV
- See `xfreight-safety-program.md` for usage

## Shipper-visibility integrations

Listed on the XFreight Presentation PDF as "ELD Integrations":

- **FourKites** — real-time freight visibility platform
- **MacroPoint** — competitor to FourKites, shipper-facing
- **Trucker Tools** — driver-facing app + visibility platform

XFreight maintains integrations with all three so any customer's preferred visibility platform is supported.

XFreight also has **EDI Capabilities** for shippers requiring electronic data interchange.

## Fuel cards

**Comdata** — primary fuel card for owner-operators (per the OO recruiting doc).

Provides:
- All applicable fuel discounts
- IFTA fuel tax reporting integration
- Cash advances (subject to deductions)
- Per-driver fuel card management

## Payment platform

**bill.com** — XFreight uses bill.com to process vendor payments (specifically Acrisure insurance payments — 8 bill.com payment screenshots are in the Acrisure reconciliation work).

## Accounting

**QuickBooks Online** — 5 separate company files (see `xfreight-quickbooks-integration.md`). Refresh tokens rotate on every API call.

## Reporting platforms

- **Power BI** — original reporting platform, reads `Alvys Master 2026.xlsx` from OneDrive
- **Google Sheets KPI Dashboard** — added later, refreshes 3x/day from APIs
- **Microsoft Outlook + OneDrive** — primary collaboration and storage

## Underwriting / insurance

- **Acrisure** (current broker, see `xfreight-insurance-and-banking.md`)
- **Great West Casualty** — primary auto/cargo carrier
- **Technology Insurance Company** — workers' comp

## Banking

- **First Dakota National Bank** — primary bank (Mike Flint, Bank Officer)
- **SBA 504 partner** — pending; lender via JB's contacts (see `xfreight-sba-504-financing.md`)

## What's NOT in the stack

Notable absences worth documenting (XFreight has evaluated and not adopted):

- **McLeod TMS** — evaluated Jan 2025, declined in favor of Alvys
- **Direct customer EDI** — uses third-party services (FourKites/MacroPoint/Trucker Tools) rather than building direct EDI per customer

## Pattern

XFreight's tech stack philosophy: **best-of-breed SaaS vs. all-in-one**. Each vendor does one thing well, integration happens via OneDrive (the pipeline) or via direct API integrations. The pipeline itself (this repo) is the "glue" that makes them feel like one system.
