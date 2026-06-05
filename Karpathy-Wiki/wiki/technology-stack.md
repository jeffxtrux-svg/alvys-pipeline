---
title: Technology Stack
type: concept
tags: [technology, vendors, tms, integrations]
sources: ["raw/xfreight-tms-and-vendor-history.md", "raw/xfreight-contact-directory.md"]
related: ["[[Data Pipeline Architecture]]", "[[Owner-Operator Program]]", "[[Safety Program]]", "[[OneDrive]]"]
---

# Technology Stack

XFreight's software vendors, SaaS integrations, and technology history — including the TMS evaluation that led to Alvys and the vendor landscape supporting operations, safety, and accounting.

## Summary

XFreight runs on best-of-breed SaaS: Alvys (TMS, current since March 2024), Samsara (telematics), QuickBooks (accounting), and SambaSafety (MVR/CSA). The pipeline repo is the glue that makes them feel like one system. McLeod TMS was evaluated in Jan 2025 and declined. The tech stack philosophy is SaaS point-solutions over all-in-one suites.

## TMS

### Alvys (current, since March 2024)

- **Onboarded:** March 2024. Onboarding contact: Reuben Sheyko (reuben.sheyko@alvys.com).
- **Manages:** loads, trips, fuel, drivers, trucks, trailers, invoices, settlements.
- **Auth:** OAuth2 client-credentials. Token cached.
- **Pipeline:** `src/main.py` → `AlvysClient` → `column_mappings.py` → `output_writer.py`.
- **Key quirks:**
  - Hybrid driver-pay model (individual OOs + OO groups) required custom settlement setup.
  - PC Miler integration for accurate mileage (Jeff asked for this at onboarding).
  - Endpoint discovery by fallback (`_fetch_with_fallback`).
  - Debug samples in `output/_debug/sample_*.json`.

### McLeod Software (evaluated Jan 2025, declined)

- JB Sweere spoke with Ryan Elmore (ryan.elmore@mcleodsoftware.com) on Jan 9, 2025.
- JB's assessment: *"I was being polite and talked to them today."*
- **Decision: stayed with Alvys.** Migration cost not justified given Alvys was already configured for XFreight's hybrid pay structure.

## Telematics

### Samsara (current)

- **Provides:** ELDs, safety events, HOS violations, DVIR defects, driver safety scores, speed-over-limit, idle time, fleet trips/IFTA.
- **Auth:** Static bearer token.
- **Cameras:** Forward-facing ONLY — no driver-facing cameras (deliberate recruiting differentiator).
- **Provided to OOs:** Samsara ELD + forward-facing camera at no cost per the [[Owner-Operator Program]].
- **Pipeline:** `src/samsara_main.py` → `SamsaraClient` → `pandas.json_normalize`.
- **Key quirk:** Fleet driver safety score uses the legacy `/v1/...` path (the modern `/fleet/drivers/{id}/safety/score` path 404s).
- **Cost:** ~$30–40/truck/month (industry standard).

## Safety + Compliance

### SambaSafety (current)

- **Provides:** MVR (Motor Vehicle Records) monitoring, driver risk index, license status + expirations, FMCSA CSA Scorecard CSV.
- **Pipeline:** `src/sambasafety_refresh.yml` reads CSVs (landed via Power Automate or manual) and writes `SambaSafety_Master.xlsx`.
- **Drives:** Pages 2 (driver compliance) and 10 (CSA Scorecard) of the brief.
- **API option:** `SAMBASAFETY_API_TOKEN` enables direct API mode, eliminating the CSV step.

## Accounting

### QuickBooks Online (current)

- Five company files. See [[QuickBooks Integration]] for full detail.
- Refresh tokens rotate on every API call — the only write-back in the pipeline.

## Carrier Onboarding

### Highway.com

- XFreight uses Highway.com for centralized carrier-packet onboarding.
- Confirmed broker connections: RL Solutions (2024-07-09), Bridge Logistics (2024-04-29).
- How it works: broker requests carrier packet via Highway → XFreight clicks accept → credentials sync.
- Dart Advantage Logistics uses a separate platform (assureassist.com).

### Broker Connections (observed)

| Broker | Connected | Platform |
|---|---|---|
| RL Solutions, LLC | 2024-07-09 | Highway.com |
| Bridge Logistics, Inc. | 2024-04-29 | Highway.com |
| Dart Advantage Logistics | 2024-01-12 | assureassist.com |

## Shipper Visibility

| Vendor | Role |
|---|---|
| **FourKites** | Real-time freight visibility (shipper-facing) |
| **MacroPoint** | Competitor to FourKites; shipper-facing |
| **Trucker Tools** | Driver-facing app + visibility |

XFreight maintains integrations with all three to support any customer's preferred platform.

**EDI:** XFreight has EDI capabilities (per the XFreight Presentation.pdf) for shippers requiring electronic data interchange.

## Fuel

### Comdata (current)

- Primary fuel card for all owner-operators.
- Provides: fuel discounts, IFTA tax reporting integration, per-driver card management, cash advances.
- Covered in weekly fuel reports (automated Monday emails, ~$7K/week average fuel spend on ~15-truck fleet).

## Payment Platform

### bill.com

- XFreight processes vendor payments (specifically Acrisure insurance) via bill.com.
- 8 bill.com payment screenshots are part of the [[Acrisure Dispute]] reconciliation work.

## Reporting

| Platform | Role |
|---|---|
| **Power BI** | Primary dashboard; reads `Alvys Master 2026.xlsx` from OneDrive. See [[Power BI]]. |
| **Google Sheets KPI Dashboard** | Parallel dashboard; refreshes 3×/day via direct API pulls. |
| **Microsoft Outlook + OneDrive** | Collaboration + file storage. |
| **GitHub Actions** | Pipeline scheduler. |
| **WeasyPrint** | PDF rendering for the 13-page daily brief. |

## Architecture Philosophy

XFreight's tech stack: **best-of-breed SaaS over all-in-one suites.** Each vendor does one thing well; integration happens via OneDrive (the pipeline) or direct API integrations. The pipeline repo (`jeffxtrux-svg/alvys-pipeline`) is the glue that makes them feel like one system.

Notable absences:
- **McLeod TMS** — evaluated Jan 2025, declined.
- **Direct customer EDI** — uses FourKites/MacroPoint/Trucker Tools instead.
- **On-prem gateway** — avoided by using Excel-in-OneDrive for Power BI.

## Connections

- [[Data Pipeline Architecture]] — the pipeline that connects these systems.
- [[Owner-Operator Program]] — Samsara + Comdata as OO benefits.
- [[Safety Program]] — Samsara + SambaSafety drive the safety pages.
- [[OneDrive]] — the staging layer.
- [[Power BI]] — the reporting layer.
- [[QuickBooks Integration]] — accounting system.

## Sources

- `raw/xfreight-tms-and-vendor-history.md`
- `raw/xfreight-contact-directory.md`
