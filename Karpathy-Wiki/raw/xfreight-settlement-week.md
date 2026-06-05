# XFreight settlement week (seeded 2026-06-05 from repo)

> Source: `src/scorecard_email.py` (`SETTLEMENT_DOW`, `SETTLEMENT_HOUR`,
> `SETTLEMENT_WEEKS`), `build_page4` (Driver mileage by settlement week).

## The cycle

A **settlement week** at XFreight runs from **Wednesday 3:00 PM Central** to the following **Wednesday 2:59 PM Central**.

Constants in `src/scorecard_email.py`:

- `SETTLEMENT_DOW = 2` (Monday=0, so Wednesday).
- `SETTLEMENT_HOUR = 15` (3pm).
- `SETTLEMENT_WEEKS = 5` — the brief shows the current partial week + 4 complete prior weeks.
- `CHI_TZ = "America/Chicago"` — all timestamps converted to this tz before windowing.

## Why Wednesday 3pm

Not documented in code comments. It's an XFreight operational convention — likely chosen so the week boundary lands mid-week / mid-day when fewer loads are in transit, simplifying which week a load's pay belongs to.

## Where it shows on the brief

- **Page 7 — Driver mileage by settlement week** (`build_page4`). Per-driver rows showing miles in each of the last 5 settlement weeks, current partial week tinted (orange bar in the email; light red in the PDF after the brand-red overhaul). Below-target tile counts drivers under `DRIVER_TARGET_MILES = 2750` mi for the **current** settlement week only.
- **Page 9 — Fleet idle** uses the same 5-settlement-week breakdown for the idle hours / idle % / idle gallons / MPG per-truck table.

## Driver mileage target

- `DRIVER_TARGET_MILES = 2750` weekly miles target (raised from 2000 in PR #88).
- The "Drivers below target · this week" tile counts drivers whose CURRENT-WEEK miles are `0 < miles < 2750`.
- Drivers with 0 miles (didn't run) aren't flagged on this tile — that's covered separately.

## Driver pay timing relative to the cycle

Owner-operator pay (the `Driver Rate` column on Alvys Loads) lands when a load **settles**, not when it delivers. There's a lag of a few days between delivery and settlement. The rate-per-mile cost-out (see `xfreight-rate-per-mile-goal.md`) filters to settled-only loads for exactly this reason — including unsettled loads would deflate the per-mile pay rate.
