# XFreight customer — J.W. Logistics (excluded from brief; carrier relationship)

> Source: `XFreight - Claude Working Files/08 - Sales/Customers/JW Logistics/Master Broker Carrier Agreement - X- Linx, INC copy 2.pdf`, NDA email threads, brief code (`_is_ar_excluded`).

## The relationship

J.W. Logistics ("JWL") is a **broker** that tenders loads to **X-Linx, Inc.** as the carrier. The contract is a Master Broker-Carrier Agreement signed **December 18, 2023**.

**Critical:** JW Logistics is **excluded from every XFreight executive report and tile** per a standing business policy. See `xfreight-jw-logistics-exclusion.md` for the policy detail and how it's enforced in code (`_is_ar_excluded()` matcher). This raw note documents the contract relationship; the policy excludes JW from reports.

## Party identifiers

### J.W. Logistics Operations, LLC (Broker)
- **MC #750864**
- Address: 3801 Parkwood Blvd, Suite 500, Frisco, TX 75034
- Phone: 855-598-7267
- Fax: 972-346-6594

### X-Linx, Inc. (Carrier)
- **MC #353490, DOT #2224732** (note: this is X-Linx's DOT, separate from X-Trux's 841776)
- Federal Tax ID #45-0452444
- Address: 47219 Hobbs Circle, Sioux Falls, SD 57103
- Phone: 605-333-0265
- Contact: Jeff Hannahs (signed Initial)

## Key terms

- **Effective Date:** December 18, 2023
- **Initial Term:** 1 year, auto-renewing for additional 1-year terms
- **Insurance required:** $100K cargo per shipment, $1M auto liability, $1M general liability, statutory workers' comp
- **JWL surety bond:** $75,000
- **Payment terms:** 30 days from undisputed invoice. Third-party payment provider used (carrier can accelerate ≈1 hour via fee).
- **Service Level:** 100% on-time deliveries required; LOS < 100% can trigger penalties or termination.
- **DOT safety rating:** Carrier must maintain "Fit," "Satisfactory," or highest available rating. Conditional/unsatisfactory = immediate disqualification.
- **Background checks:** Carrier must conduct on all drivers (InfoMart recommended).
- **No re-brokering** without consent.

## Carrier obligations (highlights)

- Maintain DOT "Fit"/"Satisfactory" rating (or highest equivalent) AND keep SMS clear of negative alerts.
- Only drivers qualified under FMCSA Part 391.
- Pre-employment screenings, Driver Information Resource, DOT Safety Management System, CSA monitoring.
- No co-loading shipper freight with other commodities.
- Waive any lien/right on shipper freight or cargo.
- Don't seek payment from Shipper directly — only from JWL.
- Don't leave shipper freight unattended/unsecured in transit.
- No unauthorized passengers.

## Non-solicitation

**2-year post-termination** non-solicit:

- Cannot solicit JWL shippers in same geographic area as awarded SOW lanes.
- Cannot solicit JWL employees or independent contractors.
- Damages: annual gross receipts of lost business + attorney fees.

## Termination

- **By JWL:** 14 days' written notice for any reason; immediate for cause (failure to perform, lost insurance, no-show, etc.).
- **By Carrier:** 30 days' written notice after first 90 days. **CANNOT terminate Nov 1 – Jan 15** of any year (peak season lockout).
- Carrier must return all JWL identification, trailers, paperwork, freight. $50/day damages if not returned promptly.

## Governing law

- **Texas law** (carrier is South Dakota corp, broker is Texas; but contract specifies Texas).

## JWL contact list

- `carriermgmt@jwlogistics.com` — contract negotiation, bidding, terms
- `payables@jwlogistics.com` — settlement, payment status, billing
- `marketing@jwlogistics.com` — uniforms
- `noc@jwlogistics.com` — operational concerns, technology

## Important context — disputes and rate questioning

The folder `08 - Sales/Customers/JW Logistics/JW Rate Questioning/` contains email correspondence about flat-rate moves (e.g. `BIS and MOT moved to Flat Rate January 22, 2024.eml`).

The folder `03 - Finance/JW Logistics Legal/` contains invoices and what looks like legal documentation. There's an invoice `Summary-Invoice-S1000067.pdf` (X-Linx INC bill to JWL, $S1000067, dated 12/5/2024).

The folder `08 - Sales/Customers/JW Logistics/` has `Re- JWL- NDA- X Freight.eml` (Aug 26, 2025) and a follow-up (Sep 2, 2025). These threads discuss NDA terms and contract concerns, specifically Section 6-a about partner relationships and existing contracts.

The **exclusion of JW from XFreight reporting** appears to be a deliberate policy connected to all of the above — disputes, legal correspondence, and the rate-questioning history. The policy keeps JW activity out of XFreight's KPI views so the reports reflect only the business that has clean accounting.
