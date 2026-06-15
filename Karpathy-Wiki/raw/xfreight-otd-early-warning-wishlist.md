# OTD early-warning view — morning wishlist (captured 2026-06-15)

> **Status:** Wishlist / not yet built. Captured from Jeff on the drive
> home as the #1 brief gap. Highest-leverage missing report — purely
> *leading* (the brief today is mostly lagging KPIs).

## What Jeff wants

A **morning view** that answers — before the day starts — **"how many
trucks are going to be late to today's deliveries, and which ones?"**

Two acceptable shapes:

- **Headline tile:** count of trucks projected late today (e.g., "3 of
  17 trucks delivering today projected late") on page 1 of the
  Operational brief, or
- **One-pager:** every driver delivering today, one row per driver,
  with current ETA vs scheduled delivery appointment and a clear
  on-time / at-risk / late flag.

The point isn't the metric — it's **planning room**. If the team sees
the risk at 5am they can call the customer, swap a load, reposition a
tractor, or set expectations *before* it becomes a service failure
explained after the fact.

## Why this is high-leverage

- The brief today reports on yesterday (lagging). This would be the
  first *forward-looking* page.
- Owns naturally to Jackson + Dan per `xfreight-employee-responsibilities.md`
  (on-time delivery; truck coverage / dispatch).
- Currently nobody has this view in one place — it's pieced together
  by checking Alvys trip details + Samsara live location ad-hoc.
- A late delivery caught at 5am is recoverable; caught at noon, it's a
  customer call after the fact.

## Data sources (already in the pipeline)

- **Alvys** — `Trips` / `Loads` / `Stops` sheets in `Alvys_Master.xlsx`:
  scheduled delivery appointment time, stop sequence, consignee,
  customer, load #. Filter to stops whose appointment falls on today
  (America/Chicago) and are still open.
- **Samsara** — `Vehicles` / `VehicleStats` sheets in
  `Samsara_Master.xlsx`: current lat/lng, speed, last-known-time per
  tractor. Combine with the destination address to compute remaining
  drive time.
- **Driver ↔ Truck join** — Alvys trip carries the driver + truck;
  Samsara is keyed by truck/asset name. Same join pattern used by the
  per-driver MPG and Speed pages in the Operational brief.

## Scoping answers (Jeff, 2026-06-15 drive home)

1. **"Late" definition.** Late = past the **delivery appointment time
   stored in Alvys**. Not the appointment window, not a buffered
   version — the appointment time itself is the line.
2. **ETA source — preference order.**
   - **Preferred:** if Alvys exposes its UI "miles to delivery" and
     "estimated time to delivery" fields via the API, use those. The
     Alvys UI already shows these for every load — same number the
     dispatcher sees should be the number the brief uses.
   - **Fallback:** build our own algorithm from Samsara current
     location → Alvys delivery address compared against the Alvys
     appointment time. Acceptable if Alvys's API doesn't expose the
     UI ETA.
   - **Investigation note.** The legacy `Alvys_Master.xlsx` schema in
     `src/column_mappings.py` (around line 847-851) already has
     placeholder columns for `Location`, `Next Stop`, `ETA`,
     `Next Appointment`, and `Location Update` — all mapped to `None`
     with the comment `# UI real-time`. That suggests whoever built
     the original mapping looked for these in the Alvys API and didn't
     find them at the time (or didn't find them on the loads/trips
     JSON shape they had). Worth re-investigating against the
     **current** API before committing to the Samsara-only fallback —
     Alvys may have added them since. Concrete first step: run the
     pipeline once, open `output/_debug/sample_loads.json` and
     `sample_trips.json`, grep for `eta`, `nextStop`, `distance`,
     `mileage`, `location`, `lastLocationAt` — if found, wire into
     those five placeholder columns AND into the OTD page.

## Still open

3. **Today scope.** Today only, or today + next 24h rolling window so
   tomorrow-AM appointments also show?
4. **Brief vs dashboard.** New page on the existing Operational brief
   (sent 5am to Jackson + Dan, Jeff cc), or a standing one-pager
   refreshed every 2h that lives somewhere else (Teams card? Sheets
   tab?). The morning brief is the right *first* surface — refreshing
   intra-day is a phase-2 ask.
5. **Status column.** Three buckets (on-time / at-risk / late) or
   five (early / on-time / tight / at-risk / late)?
6. **Who's the audience.** Jackson + Dan primary (they can act),
   Jeff cc. Audra not on this — it's operational, not safety.

## What "done" looks like

A new page on the Operational brief titled "Today's deliveries —
on-time risk" with:

- Header tile: `X of Y trucks projected late today` (colored red ≥1).
- Sortable table: Driver · Truck · Customer · Stop city · Appt time
  (CT) · Current location · Remaining drive · ETA · Slack vs appt ·
  Status pill.
- Sorted by status (Late → At-risk → On-time), then by Appt time.
- Action items written under Jackson + Dan's `owner:` field on the
  Risk Watch strip.

## Next steps

- Hold for Jeff's answers to the scoping questions above before
  building.
- Once scoped, this is an additive page on the Operational brief —
  doesn't touch the Safety brief or the executive scorecard.
