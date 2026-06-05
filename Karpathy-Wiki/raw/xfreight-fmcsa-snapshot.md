# XFreight FMCSA carrier profile (seeded 2026-06-05 from Outlook + DOT folder)

> Source: SambaSafety "CSA Scorecard - Driver List" emails from Audra Newman
> (May 2026), `06 - Safety & Compliance/DOT/USDOT_841776_All_BASICs_MotorCarrier_*`
> CSV exports, MCMIS Company Safety Profile PDF.

## X-Trux carrier identity (per FMCSA)

| Field | Value |
|---|---|
| **DOT #** | 841776 |
| **MC #** | 375851 |
| **Snapshot date** | 2026-03-27 (per the SambaSafety CSV) |
| **FMCSA data last checked** | 2026-04-08 |
| **Avg Power Units** | **26.70** |
| **Drivers (per MCS150)** | 25 |
| **Hazmat Carrier** | No |
| **Passenger Carrier** | No |

## ⚠️ Correction to earlier seed

The first batch of /raw files (`xfreight-carrier-identity.md`) cited "67 active power units" based on a value I thought was on the page-10 CSA scorecard tile. The **FMCSA-reported avg power units is actually 26.70**, not 67. Sources of confusion:

- FMCSA `AvgPowerUnits` (in the snapshot CSV / scorecard) = 26.70 — count of power units the carrier reports to FMCSA via MCS-150
- **Actual active trucks** (per Jeff's confirmation) = ~15
- The brief's Page-1 "Active Trucks · MTD" tile (live from Alvys) is the live count of trucks running loads = ~15

The 26.70 figure represents power units in inventory or registered with FMCSA but not necessarily on the road. The gap between 26.70 registered and 15 active aligns with the fleet shrinkage trend (was 23.4 in late 2024, now ~15).

There is no situation where X-Trux has 67 trucks — my prior note was wrong.

## CSA report files (in OneDrive)

- `06 - Safety & Compliance/DOT/USDOT_841776_All_BASICs_MotorCarrier_10-25-2024.xlsx` — Oct 25, 2024 BASIC categories snapshot
- `06 - Safety & Compliance/DOT/USDOT_841776_All_BASICs_MotorCarrier_11-28-2025.xlsx` — Nov 28, 2025 BASIC categories snapshot
- Two snapshots ~13 months apart — useful for tracking BASIC percentile trends

## MCMIS Company Safety Profile

PDF at `jbsweere_xfreight_net/Documents/Microsoft Teams Chat Files/COMP841776_jb0257_428202610853.pdf` — generated 04/28/2026.

This is the **full FMCSA Company Safety Profile** report for X-Trux. 215 pages covering:
- Selection criteria: Crash Detail Date 4/28/2024 – 4/28/2026 (2-year history)
- Inspection Sum Date and Crash Sum Date same range
- All inspection types, all jurisdictions

Authoritative source for FMCSA inspection and crash data. The pipeline doesn't currently parse this PDF; the data flows in via the SambaSafety CSA Scorecard CSV instead.

## How the brief's page-10 CSA scorecard works

The brief's page-10 (added in this session, per `xfreight-recent-decisions-2026-06-05.md`):

1. Reads `CSA2010 Preview Scorecard.csv` from OneDrive (manually saved from SambaSafety or auto-saved via Power Automate)
2. `compute_csa_scorecard` parses the CSV (in `src/scorecard_email.py`)
3. Renders BASIC percentile ranks
4. Each BASIC gets INTERVENTION LIKELY flag at FMCSA's `_CSA_INTERVENTION` thresholds:
   - Unsafe Driving: 65th
   - Crash Indicator: 65th
   - Maintenance, HOS, Hazmat, Driver Fitness, Controlled Substances: 80th

The page renders X-Trux carrier identity headline (DOT #841776 + MC #375851) plus the per-BASIC table.

## MCS-150 update cadence

X-Trux must update its MCS-150 (Motor Carrier Identification Report) **biennially** with FMCSA. The 26.70 power units + 25 drivers numbers are from the most recent filing. Next update due based on the schedule from the last filing.

If actual fleet has shrunk to ~15, an MCS-150 update would lower the reported power units — which could either:
- Improve some BASIC percentiles (smaller fleet, fewer total inspections to compare against)
- Affect insurance ratings (fewer units = different rate band)

This is a regulatory housekeeping task worth tracking.

## Driver list from FMCSA-reported data

Per the SambaSafety CSV: 25 drivers in the MCS-150 driver count. Matches roughly to the 21 named drivers in `XFreight Goals.xlsx` plus turnover.
