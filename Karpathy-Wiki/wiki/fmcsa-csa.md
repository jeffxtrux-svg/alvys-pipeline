---
title: FMCSA CSA Scorecard
type: concept
tags: [safety, fmcsa, csa, compliance, carrier-profile]
sources: ["raw/xfreight-fmcsa-snapshot.md", "raw/xfreight-carrier-identity.md", "raw/xfreight-safety-program.md"]
related: ["[[Safety Program]]", "[[XFreight Entities]]", "[[Daily Scorecard Email]]"]
---

# FMCSA CSA Scorecard

X-Trux's FMCSA carrier profile and CSA (Compliance Safety Accountability) BASIC percentile ranks. Page 10 of the [[Daily Scorecard Email]] renders the scorecard from the SambaSafety `CSA2010 Preview Scorecard.csv`.

## Summary

X-Trux, Inc. (DOT #841776) is an active FMCSA-regulated carrier. The SambaSafety CSA Scorecard CSV (landed daily in OneDrive via Power Automate) is parsed by `compute_csa_scorecard` and rendered as BASIC percentile ranks on page 10. INTERVENTION LIKELY flags fire at FMCSA-published thresholds.

## Key Ideas

- **DOT #841776 / MC #375851** are the authoritative identifiers for X-Trux. Hardcoded in `src/scorecard_email.py`.
- **Active fleet ≈ 15 trucks** (live from Alvys). FMCSA MCS-150 reports 26.70 avg power units — higher because it includes registered-but-idle units.
- **FMCSA-reported driver count (MCS-150):** 25 — matches roughly to the 21-driver roster + turnover.
- The page-10 scorecard fails soft: if the CSV is absent, the page renders "data unavailable."

## Carrier Identity

| Field | Value |
|---|---|
| Legal name | X-Trux, Inc. |
| DOT # | **841776** |
| MC # | **375851** |
| Snapshot date | 2026-03-27 (per SambaSafety CSV) |
| FMCSA data last checked | 2026-04-08 |
| Avg Power Units (MCS-150) | 26.70 |
| Drivers (per MCS-150) | 25 |
| Hazmat Carrier | No |

**Note:** A prior seed file incorrectly cited "67 active power units." The correct FMCSA MCS-150 figure is **26.70**, and the actual active fleet is ~15. The 67 was a misread.

## CSA BASIC Intervention Thresholds

| BASIC Category | INTERVENTION LIKELY at | Why sooner? |
|---|---|---|
| Unsafe Driving | **65th percentile** | Directly correlates with public-safety risk |
| Crash Indicator | **65th percentile** | Same |
| Maintenance | 80th percentile | |
| HOS Compliance | 80th percentile | |
| Hazardous Materials | 80th percentile | |
| Driver Fitness | 80th percentile | |
| Controlled Substances / Alcohol | 80th percentile | |

WATCH status fires at 75% of the intervention threshold; OK below that. These thresholds are in `_CSA_INTERVENTION` in `src/scorecard_email.py`.

## How the Page-10 Scorecard Works

1. SambaSafety emails `CSA2010 Preview Scorecard.csv` daily.
2. Power Automate flow (or manual drop) saves it to `OneDrive/SambaSafety/`.
3. The SambaSafety merge job (2:30am CT) reads and writes `SambaSafety_Master.xlsx` with the CSV as a sheet.
4. The scorecard email (5am CT) calls `compute_csa_scorecard` → renders page 10.
5. Each BASIC gets INTERVENTION LIKELY / WATCH / OK flag per `_CSA_INTERVENTION`.
6. Page header: "FMCSA CSA SCORECARD · X-TRUX, INC. · DOT #841776 · MC #375851".
7. Fails soft: if CSV absent, renders "data unavailable" notice.

## CSA Snapshot Files in OneDrive

- `06 - Safety & Compliance/DOT/USDOT_841776_All_BASICs_MotorCarrier_10-25-2024.xlsx` — Oct 2024 snapshot.
- `06 - Safety & Compliance/DOT/USDOT_841776_All_BASICs_MotorCarrier_11-28-2025.xlsx` — Nov 2025 snapshot.

Two snapshots 13 months apart — useful for tracking BASIC percentile trends.

## MCMIS Company Safety Profile

PDF at `jbsweere_xfreight_net/Documents/Microsoft Teams Chat Files/COMP841776_jb0257_428202610853.pdf` (generated 04/28/2026). Full 215-page profile covering 2-year crash and inspection history. The pipeline does not currently parse this PDF.

## MCS-150 Update

X-Trux must update its MCS-150 **biennially** with FMCSA. With the active fleet shrunk to ~15 trucks (vs 26.70 FMCSA-reported), an MCS-150 update would lower the reported power unit count. This could affect:
- BASIC percentile denominator (smaller fleet → fewer total inspections compared against).
- Insurance rate bands.

This is a regulatory housekeeping task worth tracking.

## How DOT Inspections Affect Scores

Each roadside inspection result → FMCSA MCMIS → BASIC score. Key retention:
- Inspections: 24 months.
- Crashes: 60 months.

Example: Brad's chafed-brake-hose violation (Mar 2026) lands in the **Maintenance BASIC**. See [[Safety Program]] for the incident detail.

## Connections

- [[Safety Program]] — daily Samsara monitoring + equipment compliance (pages 2–6).
- [[XFreight Entities]] — DOT #841776 belongs to X-Trux, not X-Linx.
- [[Daily Scorecard Email]] — page 10 renders the scorecard.

## Sources

- `raw/xfreight-fmcsa-snapshot.md` — FMCSA data + correction note.
- `raw/xfreight-carrier-identity.md` — DOT/MC numbers pinned in code.
- `raw/xfreight-safety-program.md` — CSA thresholds + page-10 logic.
