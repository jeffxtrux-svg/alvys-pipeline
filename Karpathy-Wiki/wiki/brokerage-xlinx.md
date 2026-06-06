---
title: Brokerage X-Linx
type: concept
tags: [brokerage, xlinx, carriers, operations]
sources: ["raw/xfreight-brokerage-relationships.md", "raw/xfreight-entities.md"]
related: ["[[XFreight Entities]]", "[[JW Logistics]]", "[[Financial Performance]]", "[[Factoring]]"]
---

# Brokerage X-Linx

X-Linx, Inc. (MC #353490) is XFreight's brokerage arm: it holds loads and tenders to third-party carriers. It is an FMCSA-licensed property broker, incorporated January 19, 1999.

## Summary

X-Linx brokers loads under its own MC authority, paying carriers and collecting from shippers. Margin target: **17.5% net** (`XLINX_MARGIN_GOAL`). 2026 YTD margins are running at 11.6% — 6 points below target. The active co-broker partner is ABT Brokerage (Fargo ND). X-Linx also acts as carrier for [[JW Logistics]] (but that relationship is excluded from all reports).

## Key Ideas

- X-Linx has its own FMCSA MC # (353490) and DOT # (2224732) — separate from X-Trux's 841776.
- Revenue collapsed from ~$185K/mo (Aug–Dec 2024) to ~$60K/mo (2026 YTD). Cause not fully documented.
- Overhead in the [[Rate-Per-Mile Goal]] cost-out: 100% of X-Linx overhead is pooled with X-Trux overhead and absorbed onto X-Trux asset miles (brokerage is priced per load, not per mile).
- The X-Linx margin goal (17.5%) is separate from the X-Trux OR-based goal (0.95 = 5% net).

## Entity Details

| Field | Value |
|---|---|
| Legal name | X-Linx, Inc. |
| MC # | 353490 |
| DOT # | 2224732 |
| Federal Tax ID | 45-0452444 |
| Incorporated | January 19, 1999 (South Dakota) |
| Address | 47219 Hobbs Circle, Sioux Falls SD 57103 |
| President / General Manager | J.B. Sweere |

## Co-Broker Partner

**ABT Brokerage** (MC #576546) — 1103 45th Ave N, Fargo ND 58102.

Co-brokering agreement (updated 2026-03-02) terms:
- Either party can provide loads OR arrange carrier, interchangeably per shipment.
- Carrier requirements: valid FMCSA authority, $1M auto + $100K cargo minimum, no unsatisfactory FMCSA rating.
- No re-brokering without consent.
- Payment: 30 days from invoice + proof of delivery.
- Term: 1 year, auto-renew, 30-day termination notice.
- Governing law: South Dakota (Minnehaha County courts).

## Historical Carrier References (2023 X-Linx Packet)

| Carrier | Contact | Phone |
|---|---|---|
| Dakota Carriers Inc | Jim Thielen (jimt@dakotacarriers.com) | 605-338-0002 |
| Colter Deutsch Trucking | Victoria Frahm (colterdeutschtrucking@gmail.com) | 507-449-7626 |
| T Brothers Trucking LLC | Ron Dengler (rondengler@tbrothers.com) | 605-333-0566 |

## X-Linx as Carrier (for JWL)

When X-Linx is the carrier (not the broker), see [[JW Logistics]]. X-Linx holds loads for JWL under the Master Broker-Carrier Agreement (Dec 2023) but this relationship is excluded from all reports.

## Financial Data and Pipeline Flows

X-Linx loads appear in Alvys with factoring metadata (Factoring Payments / Fee / Escrow / Commissionable Amount / Invoicing Method / Carrier Sales Agent / CSR). These are exported to:

- `04 - Brokerage X-Linx/export-700.xlsx` — last 700 loads.
- `04 - Brokerage X-Linx/carrier.xlsx` — carrier-side load reference.
- `02 - Power BI/X-Linx PBI.xlsx` / `X-Linx PBIV1.xlsx` — legacy Power BI source workbooks.

X-Linx P&L data flows through the QB connector to the `QuickBooks/QB_*.xlsx` OneDrive files. The page-1 entity P&L tile shows X-Linx margin vs the 17.5% goal.

## Revenue Trend

| Period | Avg Revenue | Avg Margin% | Avg Margin $ |
|---|---|---|---|
| 2024 (Aug–Dec) | ~$185K/mo | 18.99% | ~$35K |
| 2025 (full year) | $92K/mo | 15.79% | $17K |
| 2026 YTD | $60K/mo | **11.58%** | $7K |

X-Linx revenue has fallen ~67% since its Aug–Dec 2024 peak. Possible causes:
- JWL exclusion/de-emphasis removing a large volume customer.
- Brokerage market softness (rates and volumes down).
- Capacity constraints (fewer X-Trux trucks to broker against).

## Connections

- [[XFreight Entities]] — X-Linx is one of the five entities.
- [[JW Logistics]] — X-Linx is the carrier side; excluded from all reports.
- [[Financial Performance]] — X-Linx revenue decline is a material issue.
- [[Rate-Per-Mile Goal]] — X-Linx overhead pooled with X-Trux.
- [[Factoring]] — eCapital's offer specifically targets the brokerage + carrier Quick Pay side.

## Sources

- `raw/xfreight-brokerage-relationships.md`
- `raw/xfreight-entities.md`
