---
title: Carrier Identity
type: concept
tags: [xfreight, fmcsa, dot, mc, compliance]
sources: ["raw/xfreight-carrier-identity.md", "raw/xfreight-entities.md"]
related: ["[[XFreight Entities]]", "[[FMCSA CSA Scorecard]]", "[[Daily Scorecard Email]]", "[[Insurance and Banking]]"]
---

# Carrier Identity

## Summary

The legal carrier of record in XFreight's operations is **X-Trux, Inc.**, with DOT #841776 and MC #375851. These numbers appear on page 10 of the daily brief and are hardcoded in the pipeline code as fallbacks.

## Key Numbers

| Field | Value |
|---|---|
| **Legal name** | X-Trux, Inc. |
| **DOT number** | 841776 |
| **MC number** | 375851 |
| **Sister company (brokerage)** | X-Linx, Inc. (DOT #2224732, MC #353490) |
| **Trade / parent brand** | XFreight |

## Active Fleet Size

- **~15 active power units** as of mid-2026 (fluctuates; see the brief's page-1 "Active Trucks · MTD" tile for the current live count).
- The FMCSA CSA scorecard shows `AvgPowerUnits = 67` in the snapshot — this is a **historical carrier-of-record snapshot** that includes power units no longer in service. **Do not use it as a fleet-size proxy.**

## Why These Numbers Are Pinned in Code

- `dot_number = "841776"` — hardcoded fallback in `compute_csa_scorecard` / `build_csa_scorecard_page` in `src/scorecard_email.py`.
- `mc_num = "375851"` — literal in the same function, displayed in the page-10 Carrier Identity tile.
- If FMCSA reassigns either number (extremely rare), update both `docs/knowledge-base/architecture.md` and the literal in `src/scorecard_email.py`.

## Where These Appear on the Brief

- **Page 1** — "Active Trucks · MTD" tile.
- **Page 10** — CSA Carrier Scorecard: headline ("Carrier: DOT #841776"), MC sub-pill ("MC #375851"), section header, and source-line footer.

## Connections

- [[XFreight Entities]] — full entity table (X-Trux, X-Linx, Truk-Way, NJ Trailers, NJ Properties).
- [[FMCSA CSA Scorecard]] — page 10 rendering; BASIC percentile ranks under DOT #841776.
- [[Insurance and Banking]] — Great West Casualty underwrites under this DOT number.
- [[Contact Directory]] — addresses, phones, entity tax IDs.

## Sources

- `raw/xfreight-carrier-identity.md`
