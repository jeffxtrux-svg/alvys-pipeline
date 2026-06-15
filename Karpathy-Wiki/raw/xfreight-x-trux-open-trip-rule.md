# X-Trux open-trip rule — exclude loads with any leg still in 'Open' (seeded 2026-06-14)

> Source: `src/scorecard_email.py:_entities_from_pipeline` after the
> June 10 rule change. Replaced the "Driver Rate > 0 settled-only"
> filter for X-Trux only.

## The rule

> *"On the X-Trux side any load that has a leg/trip in 'Open' status,
> the load revenue or cost should not be counted at all until all legs
> are Covered / In Transit / Delivered / Completed / Invoiced /
> Released."* — operator spec, June 10.

A multi-leg X-Trux load doesn't contribute to MTD revenue or MTD cost
on the brief's entity P&L table until **every** trip on that load has
moved past `Open`. The instant any leg is still pending dispatch, the
whole load is excluded — both sides — to avoid the revenue-without-
cost asymmetry that drags margin % up unrealistically during the
month.

## Why this exists

The asset-trucking P&L had three problems on the way to today's rule:

1. **Booked revenue, no cost yet** — early in the month, a load can
   be booked (revenue captured in the workbook) but the driver pay
   hasn't been entered yet. Margin % shows 100% on those rows until
   settlement, dragging the MTD margin % up.
2. **Multi-leg in-flight loads** — XFreight runs multi-stop loads
   where each leg is a distinct trip. If leg 1 is delivered and leg
   2 is still queued (`Open`), the load's revenue is partially
   earned but the cost picture is incomplete.
3. **Power BI parity** — PBI's tile uses a `Driver Rate > 0` filter
   to dodge the unsettled-load distortion. That filter is a proxy
   for "the load has progressed past booking" — but it drops loads
   that PBI shouldn't exclude (e.g., fully-covered loads where
   driver pay just hasn't been entered yet) and includes loads that
   probably shouldn't count (e.g., loads where one driver has been
   paid for leg 1 but the rest of the trip is open).

The open-trip rule is more direct than PBI's "Driver Rate > 0"
proxy: it gates on the actual trip status the operator can see in
the Alvys TMS.

## How it's implemented

`compute_alvys_entities` sources from `Alvys Pipeline.xlsx` Trips
(not the Master Loads sheet — see the Pipeline-Trips source-of-truth
section). The Trips sheet has one row per trip with a `Trip Status`
column.

```python
# In _entities_from_pipeline, after the Trips sheet is loaded:
status_col = "Trip Status" if "Trip Status" in t.columns else ...
t["__open"] = t[status_col].astype(str).str.strip().str.lower() == "open"

# Aggregate by Load #:
open_flags = t.groupby("__load_id")["__open"].any().rename("any_trip_open")

# Then in the X-Trux branch:
if ent == "X-Trux":
    n_dropped = int(rows["any_trip_open"].sum())
    rows = rows[~rows["any_trip_open"]]
    if n_dropped:
        log.info("dropped %d loads with any trip in 'Open' status", n_dropped)
```

`any()` on the per-load group catches the case where *any* trip is
open, even if other trips on the same load are already in transit.

## Statuses that **count** (load is NOT dropped)

- Covered
- Dispatched
- In Transit
- Delivered
- Completed
- Invoiced
- Released

These are all the post-Open statuses Alvys exposes on a trip record.

## Status that disqualifies

- **Open** — the load drops from both revenue and cost the moment any
  leg has this status.

## What about Cancelled trips?

Cancelled trips don't trigger the open-trip drop (a cancelled leg is
not an open leg). They're handled separately in the trip-aggregation
step — cancelled trips are filtered out **before** the
groupby-and-first-rate pick, so they don't contribute carrier rate
to the picked row either.

## Scope

The rule applies **only to the X-Trux entity** in the page-1 entity
P&L table.

- **X-Linx (brokerage)** is unaffected — there's no asset-level trip
  state to wait on; the broker books revenue when the load is booked
  and the carrier rate lands at book time too.
- **KPI tiles, trend charts, AR reconciliation, dashboard sections
  other than the entity P&L** still use whichever filter was
  previously in place (most commonly the "Driver Rate > 0" filter
  from `_alvys_metrics`). Broadening the open-trip rule to those
  sections is a follow-up if their tiles drift from the entity
  table.

## Operational notes

- A diagnostic log line `dropped N loads with any trip in 'Open' status`
  prints during every scorecard run so it's clear how many loads are
  being held back.
- The 9 loads we observed dropped on the first run after the rule
  shipped (X-Trux MTD revenue moved from \$192k → \$148k) were all
  legitimately mid-trip — they reappeared in the next day's MTD once
  their open legs were dispatched.

## Related

- `xfreight-pipeline-trips-source-of-truth.md` — the data path that
  feeds the open-trip filter (Trips sheet of `Alvys Pipeline.xlsx`).
- `xfreight-power-bi.md` — why PBI's "Driver Rate > 0" filter
  exists and how this rule differs.
- `xfreight-daily-scorecard-email.md` — where the entity P&L table
  lives in the brief.
