# XFreight customer portfolio (seeded 2026-06-05 from OneDrive)

> Source: SharePoint folder map of `08 - Sales/Customers/` and `08 - Sales/Customers/Bids/`.

## Active and historical customers

Each customer has its own folder in `08 - Sales/Customers/{Customer Name}/`. Status notes are inferred from file dates and the presence of rate agreements / RFP responses.

| Customer | Status | Notes |
|---|---|---|
| **AGCO** | RFP active (Round 1 closed Dec 2025) | Ag equipment manufacturer; $50M+ annual TL spend; X-Trux + X-Linx joint bid. See `xfreight-customer-agco-rfp.md`. |
| **Amcor** | Customer (status TBD) | Global packaging manufacturer. Folder exists; content not yet reviewed. |
| **Billion Auto** | Active rate agreement, expiring **06/01/2026** | Dedicated 2-lane SF↔Rapid City + SF→Worthington→Mason City circuit. $2,150/day total revenue. See `xfreight-customer-billion-auto.md`. |
| **CMG** | RFP historical (Nov 2023) | 53' dry van, packaging materials, Auburn IN origin. `Revised CMG RFP_Carrier Lanes.xlsx`. |
| **DAG** | Customer (status TBD) | Folder exists; content not yet reviewed. |
| **Dakotaland** | Customer (status TBD) | Regional name suggests local SD customer. Folder exists; content not reviewed. |
| **JW Logistics** | Carrier-relationship + EXCLUDED FROM REPORTS | Long-standing customer with disputes and legal correspondence. See `xfreight-customer-jw-logistics.md` and `xfreight-jw-logistics-exclusion.md`. |
| **Lanter** | Customer (status TBD) | Folder exists; content not reviewed. |
| **Lewis Drug** | Customer (status TBD) | Regional pharmacy chain (Sioux Falls based). Folder exists; content not reviewed. |
| **Sazarac** (also spelled Sazerac) | RFP responded (May 2025) | Liquor distributor. TL + intermodal bid. `Sazerac RFP Due 5-6 EOD.xlsx`. |
| **Textron** | RFP historical (Nov 2023) | 236 lanes, X-Trux base rates. Big past opportunity; status of any award TBD. |
| **Twin City Fan** | Customer (status TBD) | Folder exists; content not reviewed. |
| **Viaflex** | Customer (status TBD) | Folder exists; content not reviewed. |

## Pipeline log (`08 - Sales/Call List and Logs/Call Log.xlsx`)

Spreadsheet tracking outbound prospecting:
- Columns: Customer Name, Email, Phone, Secondary Email, City, State, Email Sent on, Response Email, Bounce, Followup Date, Notes, Stage
- Example: EVERGREEN OFFICE PRODUCTS (evergreenlyle@ttcrc.com)

This is the **sales prospecting pipeline** — different from the Customers/ folder which is for live or recent customers. Last touched 2025-10-30.

## Leads List (`08 - Sales/Call List and Logs/Leads List.xlsx`)

A prospect database with:
- Good Lead (Yes/No)
- Contacted, Contact Title, Email, Phone, Mobile
- Name, Address, Company Number, Type, Status
- Shipping Hours, MC, USDOT, Billing

Industry-standard "carrier prospecting" data. Last touched 2025-10-30.

## RFPs in progress / recent

### AGCO (active, decision pending Q1 2026)
- Round 1 closed Dec 10
- Carrier selection week of Dec 22, 2025
- Rates effective Feb 1, 2026 through Jan 31, 2027
- See `xfreight-customer-agco-rfp.md` for full detail

### Sazerac (responded May 2025)
- File: `Sazerac RFP Due 5-6 EOD.xlsx` (also `EOD1.xlsx`)
- TL + intermodal bid
- High-theft commodity (liquor)

### CMG (Nov 2023, historical)
- File: `Revised CMG RFP_Carrier Lanes.xlsx`
- Outbound Auburn IN packaging materials, 53' dry van

### Textron (Nov 2023, historical)
- File: `Textron Bid 236 Lanes 11-16-23.xlsx`
- 236 lanes
- X-Trux base rates
- Status of award not captured in surfaced files

## Where customer business signals show up

- **Page 1 entity tiles** (brief) — show X-Trux + X-Linx aggregate revenue. Customer-level detail not visible at this layer.
- **Page 12 (QB-vs-Alvys reconciliation by customer)** — per-customer variance. This is the page where individual customer issues surface.
- **AR aging tiles + page 11 AR overdue list** — overdue invoices by customer, JW Logistics excluded.

## Strategic concentration risk

Without seeing each customer's revenue contribution, can't quantify exactly. But:
- JW Logistics historically large but disputed (now excluded)
- Billion Auto is a daily-volume customer ($2,150/day × ~22 days = ~$47K/month revenue, dependable but lower-margin)
- AGCO would be transformative if awarded — could be $5-10M+/year if XFreight wins major lanes

Worth pulling QB customer revenue split next time the reconciliation page surfaces it.
