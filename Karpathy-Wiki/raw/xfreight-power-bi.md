# XFreight Power BI report (seeded 2026-06-05 from repo)

> Source: `docs/knowledge-base/powerbi.md`, `CLAUDE.md` configuration section,
> `powerbi/` folder in the repo.

## What it is

The legacy reporting layer that XFreight's team uses day-to-day. Reads `Alvys Master 2026.xlsx` from OneDrive and renders a multi-page Power BI report covering loads, revenue, deadhead, RPM, driver mileage, customer breakdowns, etc.

## The "Excel-in-OneDrive" coupling

Power BI was the entire reason the pipeline doesn't use a database. Reasons:

- **No on-prem gateway needed.** Power BI's OneDrive/SharePoint connector reads files directly without a self-hosted gateway, which would otherwise be required for SQL/Postgres.
- **The business already had a hand-maintained `Alvys_Master.xlsx`.** Matching its schema let the existing report keep working with zero rebuild — a 200-column tuple-driven mapping in `src/column_mappings.py`.
- **Debuggable by non-engineers.** Open the file, look at the cells, see what Power Query will see.

The tradeoff is the awkward "iterate the pipeline then refresh Power BI" loop and file locks if anyone has the workbook open during a write. Accepted.

## File naming rule (the critical one)

- **`Alvys Master 2026.xlsx`** — HAND-MAINTAINED. Power BI reads this.
- **`Alvys Pipeline.xlsx`** — pipeline-written. Different filename, on purpose.

If the pipeline ever wrote to `Alvys Master 2026.xlsx`, it would overwrite the manual workbook and break the Power BI report. The CI workflow has `ONEDRIVE_TARGET_FILENAME: "Alvys Pipeline.xlsx"` baked into `refresh.yml` to prevent this.

The daily scorecard email ALSO reads `Alvys Master 2026.xlsx` (not the pipeline output) so its KPIs match Power BI exactly.

## The 200-column schema

`src/column_mappings.py` is a large declarative list of `(excel_column_name, accessor)` tuples. The accessor is either a dotted path string (`"Stops.first.Address.City"`) or a callable. `src/transformers.py` walks each mapping per record and assembles the output row.

This exists ONLY because the legacy `Alvys_Master.xlsx` has 200 specific column headers, and the Power BI report's Power Query "Changed Type" steps were authored against those exact formats. Changing a column name in the pipeline output requires either updating Power Query OR changing the mapping back.

When an Alvys column comes back blank, the field path in `column_mappings.py` is wrong — open `output/_debug/sample_loads.json` (or `_trips`/`_fuel`/`_invoice`), find the real path, fix the one tuple, re-run. The log's `report_blank_columns` lists what's still empty.

## Date formatting quirk

`src/output_writer.py` is deliberately fussy: it reproduces the legacy file's exact date format (`MM-DD-YYYY` text, America/Chicago) and integer ID columns, because Power Query "Changed Type" steps were authored against those exact formats. Changing the date format in the pipeline breaks Power BI's column typing.

## The Power BI-reads-Alvys-directly POC

`powerbi/` folder holds a proof-of-concept where Power BI reads the Alvys API directly via Power Query (`.pq`) files plus DAX measures. Bypasses the Excel intermediate entirely.

Not yet adopted as the primary flow. The current Excel pipeline + Power BI is the production path.

## load↔QB join key

For the QB-vs-Alvys reconciliation reports (and any Power BI cross-source measure), the matching key is:

- **Alvys** `Load #` column
- **QuickBooks** `"T" + load #` invoice `Num`

The brief's `_norm_inv()` helper strips a leading alpha prefix to make them match.
