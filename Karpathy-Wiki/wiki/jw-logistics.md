---
title: JW Logistics
type: concept
tags: [customers, exclusion, disputes, legal]
sources: ["raw/xfreight-customer-jw-logistics.md", "raw/xfreight-jw-logistics-exclusion.md", "raw/xfreight-active-disputes-and-issues.md"]
related: ["[[Customer Portfolio]]", "[[Brokerage X-Linx]]", "[[XFreight Entities]]"]
---

# JW Logistics

J.W. Logistics Operations, LLC is a freight broker that tenders loads to X-Linx, Inc. as the carrier. The relationship is governed by a Master Broker-Carrier Agreement (Dec 2023) but **JW Logistics is excluded from every XFreight executive report and KPI tile** by a standing business policy.

## Summary

JWL (MC #750864, Frisco TX) signed a carrier agreement with X-Linx (MC #353490) on December 18, 2023. Despite being an active carrier relationship, rate disputes, legal correspondence, and AR distortion led XFreight to exclude JWL from all reporting. The hardened `_is_ar_excluded()` and `_is_excluded_truck()` matchers in `src/scorecard_email.py` enforce this.

## Key Ideas

- The exclusion is **permanent and hardened** — even a typo in QB's customer list can't bypass it.
- JWL must NOT appear in any new page, tile, or aggregation without routing through the exclusion matchers.
- Contract allows JWL to terminate with 14 days' notice; X-Linx cannot terminate Nov 1–Jan 15 (peak season lockout).
- 2-year post-termination non-solicitation clause: X-Linx cannot solicit JWL's shippers in the same lanes.

## The Exclusion Policy

**Rule:** JW Logistics is treated as if it doesn't exist for:
- Page-1 entity tiles (revenue, margin, loads, miles).
- All five AR aging buckets (Current / 1–30 / 31–60 / 61–90 / 91+).
- QB-vs-Alvys reconciliation (page 12) and bill-by-bill match (page 13).
- 90+ collections list.
- Samsara safety/fleet metrics where unit labels carry the JW prefix.

**How it's enforced:**
- `_is_ar_excluded()` in `src/scorecard_email.py` — case-insensitive, handles whitespace, handles common spellings.
- `_is_excluded_truck()` — filters JW truck units from Samsara aggregations including the headline fleet total (bug fixed in PR #88).

**Why it exists:** Not documented in code comments. Likely connected to rate disputes (`JW Rate Questioning/` folder), late/short payments distorting AR aging, and legal correspondence (`03 - Finance/JW Logistics Legal/`). The policy pre-dates the period covered by these source files.

**If the policy changes:** Update only `src/scorecard_email.py` matchers. The exclusion is testable.

## Carrier Agreement Terms

- **Effective Date:** December 18, 2023
- **Initial term:** 1 year, auto-renewing annually.
- **Insurance:** $100K cargo / $1M auto liability / $1M general liability / statutory workers' comp.
- **JWL surety bond:** $75,000.
- **Payment terms:** 30 days from undisputed invoice.
- **Service level:** 100% on-time deliveries; shortfalls can trigger termination.
- **Governing law:** Texas.

## Active Dispute Context

- `03 - Finance/JW Logistics Legal/` contains invoice `Summary-Invoice-S1000067.pdf` (X-Linx → JWL, 12/5/2024) and other dispute documents.
- NDA negotiations ongoing (Aug–Sep 2025 email threads, referencing Section 6-a about partner relationships).
- Rate disputes in `08 - Sales/Customers/JW Logistics/JW Rate Questioning/` (flat-rate moves Jan 2024).

## Party Identifiers

| Party | Role | MC # | DOT # | Address |
|---|---|---|---|---|
| J.W. Logistics Operations, LLC | Broker | 750864 | — | 3801 Parkwood Blvd Suite 500, Frisco TX 75034 |
| X-Linx, Inc. | Carrier | 353490 | 2224732 | 47219 Hobbs Circle, Sioux Falls SD 57103 |

## JWL Contacts

- carriermgmt@jwlogistics.com — contract / terms
- payables@jwlogistics.com — settlement / payment
- marketing@jwlogistics.com — uniforms
- noc@jwlogistics.com — operational / tech issues

## X-Linx Revenue Impact

X-Linx brokerage revenue collapsed from ~$185K/month (Aug–Dec 2024) to ~$60K/month (2026 YTD). The JWL exclusion/de-emphasis is a plausible contributor, though the precise share is not documented.

## Connections

- [[Customer Portfolio]] — JWL in context of the full book.
- [[Brokerage X-Linx]] — X-Linx is the carrier side of the JWL relationship.
- [[Financial Performance]] — X-Linx revenue decline may be partly attributable to JWL.
- [[XFreight Entities]] — X-Linx DOT/MC numbers differ from X-Trux.

## Sources

- `raw/xfreight-customer-jw-logistics.md` — contract terms.
- `raw/xfreight-jw-logistics-exclusion.md` — policy and code enforcement.
- `raw/xfreight-active-disputes-and-issues.md` — dispute context.
