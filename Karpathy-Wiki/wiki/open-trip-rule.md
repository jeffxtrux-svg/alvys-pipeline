---
title: X-Trux Open-Trip Rule
type: concept
tags: [operations, pipeline, entity-pl, x-trux, trips, brief]
sources: ["raw/xfreight-x-trux-open-trip-rule.md"]
related: ["[[Data Pipeline Architecture]]", "[[Daily Scorecard Email]]", "[[Financial Performance]]", "[[Power BI]]", "[[XFreight Entities]]"]
---

# X-Trux Open-Trip Rule

The X-Trux open-trip rule governs which loads are counted in the entity P&L on page 1 of the [[Daily Scorecard Email]]. Any X-Trux load that has even one trip leg still in `Open` status is excluded from both revenue and cost until every leg has moved past Open — preventing the margin distortion caused by booked-but-not-yet-moving loads.

## The Rule

> *"On the X-Trux side any load that has a leg/trip in 'Open' status, the load revenue or cost should not be counted at all until all legs are Covered / In Transit / Delivered / Completed / Invoiced / Released."* — operator spec, June 10, 2026.

A multi-leg X-Trux load contributes nothing to MTD revenue or MTD cost on the entity P&L until **every** trip on that load has moved past `Open`. The moment any leg is still pending dispatch, the whole load is excluded — both sides — to avoid inflating the apparent margin % with revenue-without-cost rows.

## Why This Rule Exists

The asset-trucking P&L had three compounding problems before this rule:

1. **Booked revenue, no cost yet** — a load can be booked (revenue captured) but the driver pay hasn't been entered. Margin % shows 100% on those rows until settlement, pulling MTD margin up unrealistically.

2. **Multi-leg in-flight loads** — XFreight runs multi-stop loads where each leg is a distinct trip. If leg 1 is delivered and leg 2 is still queued (`Open`), the load's revenue is partially earned but the cost picture is incomplete.

3. **Power BI proxy mismatch** — Power BI's tile uses a `Driver Rate > 0` filter to dodge the unsettled-load distortion, but that filter excludes legitimately-covered loads where driver pay just hasn't been entered yet, and includes loads where only some legs have settled. The open-trip rule is more direct: it gates on the actual trip status visible in the Alvys TMS.

## How It's Implemented

Source data: `Alvys Pipeline.xlsx` Trips sheet (one row per trip, with a `Trip Status` column). Not the Master Loads sheet.

```python
# In _entities_from_pipeline:
t["__open"] = t[status_col].str.strip().str.lower() == "open"

# Aggregate by Load #:
open_flags = t.groupby("__load_id")["__open"].any().rename("any_trip_open")

# X-Trux branch only:
if ent == "X-Trux":
    rows = rows[~rows["any_trip_open"]]
```

`any()` catches the case where any single trip on a load is open, even if other trips on the same load are already in transit or delivered.

## Statuses That Count (load is NOT excluded)

- Covered
- Dispatched
- In Transit
- Delivered
- Completed
- Invoiced
- Released

## Status That Disqualifies

- **Open** — the load drops from both revenue and cost as long as any leg has this status.

## Cancelled Trips

Cancelled trips do NOT trigger the open-trip drop. They're filtered out before the groupby/rate-pick step, so they don't contribute carrier rate to the picked row either. A load with a cancelled leg and all other legs Covered proceeds normally.

## Scope — X-Trux Only

The rule applies **only to X-Trux** in the page-1 entity P&L table:

- **X-Linx (brokerage):** unaffected — there's no asset-level trip state to wait on; broker books revenue and carrier rate at load time.
- **KPI tiles, trend charts, AR reconciliation, and other brief sections** continue to use whichever filter was previously in place (most commonly the `Driver Rate > 0` filter from `_alvys_metrics`).

## Operational Impact

On the first run after the rule shipped (June 10, 2026): 9 loads dropped from X-Trux MTD — revenue moved from $192K → $148K. All 9 were legitimately mid-trip and reappeared in the next day's MTD once their open legs were dispatched.

A diagnostic log line prints on every scorecard run: `dropped N loads with any trip in 'Open' status` — so it's always clear how many loads are being held back.

## Connections

- [[Daily Scorecard Email]] — page 1 entity P&L table is where this rule applies.
- [[Financial Performance]] — MTD revenue figures reflect this filter.
- [[Data Pipeline Architecture]] — Trips sheet is the source; `compute_alvys_entities` applies the rule.
- [[Power BI]] — Power BI uses the `Driver Rate > 0` proxy instead; the two approaches can produce slightly different MTD numbers.
- [[XFreight Entities]] — rule is X-Trux only; X-Linx entity P&L is unaffected.

## Sources

- `raw/xfreight-x-trux-open-trip-rule.md` — operator spec (June 10, 2026), implementation detail, and observed impact.
