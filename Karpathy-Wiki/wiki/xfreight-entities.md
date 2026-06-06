---
title: XFreight Entities
type: concept
tags: [entities, company-structure, accounting]
sources: ["raw/xfreight-entities.md", "raw/xfreight-contact-directory.md", "raw/xfreight-carrier-identity.md", "raw/xfreight-truk-way-leasing.md"]
related: ["[[Key People]]", "[[Truk-Way Leasing]]", "[[QuickBooks Integration]]", "[[JW Logistics]]"]
---

# XFreight Entities

XFreight is operated through five legal entities — three active in the pipeline and two reserved for future use.

## Summary

The operating group consists of **X-Trux, Inc.** (asset trucking carrier), **X-Linx, Inc.** (freight brokerage), and **Truk-Way Leasing, LLC** (equipment leasing + employer of record for W-2 staff). Two future entities — **N&J Trailers** and **N&J Properties, LLC** — have QB company-file slots but no active refresh tokens; they are expected to come online after the [[SBA 504 Financing]] closes.

## Key Ideas

- X-Trux + X-Linx are the "XFreight" reporting pair — every brief and KPI tile is scoped to these two.
- [[JW Logistics]] is excluded from all reports via the hardened `_is_ar_excluded()` matcher.
- Truk-Way is the employer of record for W-2 office staff (Audra, dispatchers, etc.) and leases trailers to X-Trux.
- The five-entity structure separates customer brands, asset ownership, employer-of-record, and future real estate.

## Entities

| Entity | DOT # | MC # | Federal Tax ID | Status |
|---|---|---|---|---|
| **X-Trux, Inc.** | 841776 | 375851 | (pending) | Live — asset carrier |
| **X-Linx, Inc.** | 2224732 | 353490 | 45-0452444 | Live — brokerage |
| **Truk-Way Leasing, LLC** | — | — | (pending) | Live — leasing + payroll |
| **N&J Trailers** | — | — | (pending) | Not live (refresh token absent) |
| **N&J Properties, LLC** | — | — | (pending) | Not live (refresh token absent) |

Both X-Trux and X-Linx are South Dakota corporations. X-Linx was incorporated January 19, 1999. Both are headquartered at 47219 Hobbs Circle, Sioux Falls, SD 57103.

## X-Trux (carrier)

- Asset-based truckload carrier; all 48 contiguous states; dry van.
- **Active fleet:** ~15 trucks (per the live "Active Trucks · MTD" tile on page 1 of the brief). FMCSA MCS-150 reports 26.70 avg power units — higher than the active count because it includes registered-but-idle units.
- Employs owner-operators under the [[Owner-Operator Program]] ($1.89/mi loaded + empty).
- DOT #841776 / MC #375851 are hardcoded in `src/scorecard_email.py` and `docs/knowledge-base/architecture.md`. If FMCSA reassigns either, update both locations.

## X-Linx (brokerage)

- Licensed FMCSA property broker (MC #353490).
- Sells loads, pays carriers. Priced per load, not per mile.
- Margin target: **17.5% net** (`XLINX_MARGIN_GOAL = 17.5%`).
- Co-broker partner: **ABT Brokerage** (MC #576546, Fargo ND). See [[Brokerage X-Linx]].
- X-Linx carries no per-mile overhead in the [[Rate-Per-Mile Goal]] cost-out; overhead is absorbed 100% by X-Trux miles.

## Truk-Way Leasing

See the dedicated page: [[Truk-Way Leasing]].

Three roles in one entity:
1. Leases trailers to X-Trux.
2. Employer of record for W-2 office staff (provides Wellmark Blue Cross health/vision insurance).
3. Payment hub for owner-operator groups (groups that have multiple trucks).

**QB Trial Balance YTD 2026:** ~$3.8M and growing ~$90K/month.

## N&J Entities (future)

Placeholder QuickBooks company files. Expected to come online after the [[SBA 504 Financing]] closes:
- **N&J Properties, LLC** — likely holds the real-estate purchase.
- **N&J Trailers** — likely additional trailer inventory.

The pipeline's `_companies()` function in `src/qb_main.py` already has env var slots (`QB_NJ_TRAILERS_REALM_ID`, etc.) that will activate once refresh tokens are seeded.

## How entities appear in the brief

- **Page 1 entity tiles** — X-Trux + X-Linx only. Combined totals at the bottom.
- **Truk-Way** — per-truck P&L tab on the Google Sheets KPI dashboard; NOT in the page-1 headline tiles.
- **JW Logistics** — excluded from every tile and report.

## Connections

- [[Key People]] — leadership tied to these entities.
- [[QuickBooks Integration]] — the five QB company files map 1:1 to these entities.
- [[Rate-Per-Mile Goal]] — overhead cost-out pools X-Trux + X-Linx expenses.
- [[SBA 504 Financing]] — expected to bring N&J entities online.
- [[JW Logistics]] — the excluded sixth entity in reports.

## Sources

- `raw/xfreight-entities.md` — entity map from CLAUDE.md + QB connector.
- `raw/xfreight-contact-directory.md` — DOT/MC/Fed IDs.
- `raw/xfreight-carrier-identity.md` — carrier identity pinned in code.
- `raw/xfreight-truk-way-leasing.md` — Truk-Way's three roles.
