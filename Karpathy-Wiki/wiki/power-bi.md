---
title: Power BI
type: concept
tags: [reporting, power-bi, excel, schema]
sources: ["raw/xfreight-power-bi.md", "raw/xfreight-onedrive-and-key-files.md"]
related: ["[[OneDrive]]", "[[Data Pipeline Architecture]]", "[[QuickBooks Integration]]"]
---

# Power BI

The legacy Power BI report that XFreight's team uses day-to-day. Reads `Alvys Master 2026.xlsx` from OneDrive (jeff@xfreight.net) and renders a multi-page report covering loads, revenue, deadhead, RPM, driver mileage, and customer breakdowns.

## Summary

Power BI reads the hand-maintained `Alvys Master 2026.xlsx` directly from OneDrive — no gateway required. The pipeline writes to `Alvys Pipeline.xlsx` (a different file name, on purpose) so it never overwrites the manual workbook. The 200-column schema in `src/column_mappings.py` exists to match the exact column headers Power BI was built against.

## Key Ideas

- **`Alvys Master 2026.xlsx` must never be overwritten by the pipeline.** CI workflow has `ONEDRIVE_TARGET_FILENAME: "Alvys Pipeline.xlsx"` baked in.
- The **date format** in `src/output_writer.py` (`MM-DD-YYYY` text, America/Chicago) must not change — Power Query "Changed Type" steps were authored against those exact formats.
- The daily scorecard email also reads `Alvys Master 2026.xlsx` (not `Alvys Pipeline.xlsx`) so its KPIs match Power BI.
- A proof-of-concept (`powerbi/` folder) exists where Power BI reads the Alvys API directly — not yet adopted as the primary flow.

## Why Excel-in-OneDrive

Power BI connects to OneDrive/SharePoint files without an on-prem gateway. The alternative (SQL/Postgres database) would require hosting, credentials, backups, and a self-hosted gateway. The business already had a hand-maintained workbook; matching its schema meant zero Power BI rebuild.

Tradeoff: file locks if anyone has the workbook open during a pipeline write; awkward pipeline-then-refresh-PBI loop. Accepted.

## The 200-Column Schema

`src/column_mappings.py` is a large declarative list of `(excel_column_name, accessor)` tuples:
- **String accessors** — dotted paths through the JSON: `"Stops.first.Address.City"`.
- **Callable accessors** — lambda/function for derived fields.
- `src/transformers.py` walks each mapping per record and assembles the output row.

This schema was not designed for the pipeline — it was reverse-engineered from the legacy hand-maintained `Alvys_Master.xlsx` to match Power BI's existing "Changed Type" steps exactly.

**When an Alvys column comes back blank:**
1. Open `output/_debug/sample_loads.json` (or `_trips`/`_fuel`/`_invoice`).
2. Find the real field path in the raw JSON.
3. Fix that one tuple in `column_mappings.py`.
4. Re-run.

The log's `report_blank_columns` lists what's still empty.

## Date Format Rule

`src/output_writer.py` writes all dates as `MM-DD-YYYY` TEXT strings in America/Chicago timezone — NOT as Excel date values. Power Query's "Changed Type" steps type these as text and then parse them. Changing the format (e.g. to ISO 8601 or an actual Excel date) would break Power BI's column typing.

## The QB ↔ Alvys Join Key

For the QB-vs-Alvys reconciliation in Power BI cross-source measures:
- **Alvys side:** `Load #` column.
- **QB side:** Invoice `Num` field, which uses convention `"T" + load number`.
- The pipeline's `_norm_inv()` strips the leading alpha prefix to make them match.

## The Direct-API Proof-of-Concept

`powerbi/` folder in the repo holds Power Query `.pq` files + DAX measures that read the Alvys API directly, bypassing the Excel intermediate entirely. Not yet adopted as the primary flow. The current Excel pipeline + Power BI is production.

## Connections

- [[OneDrive]] — Power BI reads `Alvys Master 2026.xlsx` from here.
- [[Data Pipeline Architecture]] — the pipeline writes `Alvys Pipeline.xlsx` (never the master).
- [[QuickBooks Integration]] — QB data feeds the AR/AP sections in Power BI via OneDrive files.
- [[Daily Scorecard Email]] — also reads `Alvys Master 2026.xlsx` for KPI consistency.

## Sources

- `raw/xfreight-power-bi.md`
- `raw/xfreight-onedrive-and-key-files.md`
