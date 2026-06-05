# X-Linx brokerage relationships (seeded 2026-06-05 from OneDrive)

> Source: `04 - Brokerage X-Linx/Co-Brokering Agreement.docx`, `aalinxpacket.pdf` X-Linx
> Company Profile + Carrier References, JWL Master Broker-Carrier Agreement.

## X-Linx as broker — co-broker agreements

X-Linx (MC #353490) acts as a property broker authorized by FMCSA. The standard co-broker agreement template is at `04 - Brokerage X-Linx/Co-Brokering Agreement.docx`.

### Active co-broker partner: ABT Brokerage

- **ABT Brokerage** — MC #576546
- Address: 1103 45th Ave N, Fargo, ND 58102
- Co-broker agreement template, updated 2026-03-02

### Co-broker agreement terms (template)

- Either party can provide load OR arrange carrier; roles interchangeable per shipment
- **Carrier selection:** valid FMCSA authority, $1M auto liability minimum, $100K cargo minimum, no unsatisfactory FMCSA rating
- **Written carrier contracts** required
- **No re-brokering** without consent
- **Payment:** 30 days from invoice + proof of delivery (between brokers)
- **Insurance:** each party maintains broker bond/insurance, provides proof on request
- **Confidentiality:** keep shipper, carrier, rate, financial info confidential
- **Term:** 1 year, auto-renew with 30-day notice termination
- **Governing law:** South Dakota (Minnehaha County courts)

## X-Linx as carrier — for JWL

When X-Linx is the carrier (not broker), see `xfreight-customer-jw-logistics.md` for the JWL Master Broker-Carrier Agreement detail. X-Linx is excluded from carrier reports by the JW Logistics exclusion policy though.

## X-Linx carrier references (from 2023 packet)

Carriers X-Linx has historically worked with — provided as references in the company packet:

| Carrier | Contact | Email | Phone |
|---|---|---|---|
| **Dakota Carriers Inc** | Jim Thielen | jimt@dakotacarriers.com | 605-338-0002 |
| **Colter Deutsch Trucking** | Victoria Frahm | colterdeutschtrucking@gmail.com | 507-449-7626 |
| **T Brothers Trucking LLC** | Ron Dengler | rondengler@tbrothers.com | 605-333-0566 |

## X-Linx address + company info

- **47219 Hobbs Circle, Sioux Falls, SD 57103**
- P.O. Box 293, Sioux Falls, SD 57104
- South Dakota Corporation, incorporated **January 19, 1999**
- President / General Manager: **J.B. Sweere** (jbsweere@xfreight.net per OneDrive scope)
- Phones: 605-543-8383 / 800-898-6061 / 605-543-8366 fax
- Email: xtrux@xfreight.net

## Brokerage data flows

X-Linx loads are pulled from Alvys and joined to QuickBooks via the standard pipeline. The brokerage page-1 entity tile uses `XLINX_MARGIN_GOAL = 17.5%` net target (carrier-pay net margin). See `xfreight-entities.md`.

X-Linx loads with their factoring metadata (Factoring Payments / Fee / Escrow / Commissionable Amount / Last Check Call / Invoicing Method / Carrier Sales Agent / Customer Service Representative) appear in:

- `02 - Power BI/X-Linx PBI.xlsx` / `X-Linx PBIV1.xlsx` (Power BI source workbooks)
- `04 - Brokerage X-Linx/export-700.xlsx` (Alvys export of last 700 loads)
- `04 - Brokerage X-Linx/carrier.xlsx` (carrier-side load reference)
- `02 - Power BI/XFreight Data.xlsx` (master Power BI feed combining both entities)
