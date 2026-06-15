---
title: X-Trux Open-Trip Rule
type: concept
tags: [pipeline, alvys, entity-pl, trips, data-quality]
sources: ["raw/xfreight-x-trux-open-trip-rule.md"]
related: ["[[Data Pipeline Architecture]]", "[[Daily Scorecard Email]]", "[[Power BI]]", "[[Rate-Per-Mile Goal]]", "[[Brokerage X-Linx]]"]
---

# X-Trux Open-Trip Rule

## Summary

On the X-Trux entity P&L table in the daily brief, any load that has at least one trip still in **Open** status is excluded entirely from both revenue and cost until every trip on that load has moved past Open. Introduced June 10, 2026 to replace the "Driver Rate > 0" filter previously used as a proxy.

## The Rule

> *"On the X-Trux side any load that has a leg/trip in 'Open' status, the load revenue or cost should not be counted at all until all legs are Covered / In Transit / Delivered / Completed / Invoiced / Released."*

A multi-leg X-Trux load doesn't contribute to MTD revenue or MTD cost until **every** trip on that load has moved past Open. The moment any leg is still pending dispatch, the whole load is excluded — both sides — to avoid the revenue-without-cost asymmetry that drags the MTD margin % up unrealistically during the month.

## Why This Exists

Three problems on the path to this rule:

1. **Booked revenue, no cost yet** — early in the month, a load can be booked (revenue captured) but driver pay not yet entered. Margin % shows 100% on those rows until settlement, inflating MTD margin %.
2. **Multi-leg in-flight loads** — XFreight runs multi-stop loads where each leg is a distinct trip. If leg 1 is delivered and leg 2 is still queued (Open), the load's revenue is partially earned but cost picture is incomplete.
3. **Power BI parity** — PBI's tile uses a "Driver Rate > 0" filter as a proxy for "the load has progressed past booking." This proxy drops loads that shouldn't be excluded (fully-covered loads where driver pay hasn't been entered yet) and includes loads that probably shouldn't count. The open-trip rule is more direct.

## Statuses That Count (load is NOT dropped)

- Covered
- Dispatched
- In Transit
- Delivered
- Completed
- Invoiced
- Released

## Status That Disqualifies

- **Open** — the load drops from both revenue and cost the moment any leg has this status.

**Cancelled trips** do not trigger the open-trip drop. They are filtered out before the groupby-and-rate-pick step so they don't contribute carrier rate to the picked row.

## Implementation

`compute_alvys_entities` sources from `Alvys Pipeline.xlsx` Trips sheet (one row per trip, `Trip Status` column):

```python
t["__open"] = t[status_col].astype(str).str.strip().str.lower() == "open"
open_flags = t.groupby("__load_id")["__open"].any().rename("any_trip_open")

# X-Trux branch only:
if ent == "X-Trux":
    n_dropped = int(rows["any_trip_open"].sum())
    rows = rows[~rows["any_trip_open"]]
    if n_dropped:
        log.info("dropped %d loads with any trip in 'Open' status", n_dropped)
```

`any()` on the per-load group catches the case where *any* trip is Open, even if other trips on the same load are in transit.

## Scope

This rule applies **only to X-Trux in the entity P&L table** (page 1).

- **X-Linx (brokerage)** is unaffected — no asset-level trip state to wait on; the broker books revenue and carrier rate at book time.
- **KPI tiles, trend charts, AR reconciliation, and other sections** still use whichever prior filter was in place. Broadening the rule to those sections is a potential follow-up.

## Operational Notes

- A diagnostic log line `dropped N loads with any trip in 'Open' status` prints on every scorecard run.
- On the first run after the rule shipped: 9 loads dropped (X-Trux MTD revenue moved from $192K → $148K). All were legitimately mid-trip — they reappeared the next day once their open legs were dispatched.

## Connections

- [[Data Pipeline Architecture]] — the Pipeline file is the source of truth for trips and entities.
- [[Daily Scorecard Email]] — the entity P&L table lives on page 1.
- [[Power BI]] — PBI's "Driver Rate > 0" filter is the prior approximation; this rule is more direct.
- [[Rate-Per-Mile Goal]] — settled-only loads feed the cost-out; this rule ensures P&L and cost-out use consistent populations.

## Sources

- `raw/xfreight-x-trux-open-trip-rule.md`
