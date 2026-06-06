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

## Weekly pay-rate revision aligned to the cycle

**The owner-op loaded + empty per-mile rate AND the fuel surcharge are revised every Wednesday** — i.e. at the start of each settlement week. This is why:

- The settlement-week cycle begins Wednesday 3pm CT rather than at a random day boundary — the rate change and the settlement boundary are intentionally aligned so each settlement week has a single per-mile rate.
- A settlement worksheet for a given driver covers loads delivered within one rate band, simplifying reconciliation.
- The `RPM_GOAL_PAY_WINDOW_DAYS = 10` trailing window in the rate-per-mile cost-out captures roughly one-and-a-half rate weeks, smoothing the week-over-week rate change into a stable read while still tracking it fast enough to be current.

See `xfreight-owner-operator-program.md` § "Weekly rate revision" for the full detail. The current week's rate is whatever was set on the most recent Wednesday; the published $1.89/mi reference is a recent baseline, not a fixed rate.
