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

**The owner-op loaded + empty per-mile rate AND the fuel surcharge are revised every Wednesday** — at the start of each settlement week.

### The dispatch date locks the rate (not delivery, not settlement)

**A load's per-mile rate is set the moment dispatch happens, based on the rate effective on that calendar day.** Concretely:

- Load **dispatched on a Tuesday** → uses **that week's** mileage rate for the entire load, even if it delivers Friday, Saturday, or the following Monday.
- Load **dispatched on Wednesday or later** → uses the **NEW** week's mileage rate.

Implications for the settlement-week cycle:

- A single settlement week (Wed 3pm CT → following Wed 2:59pm CT) typically contains **loads at two different per-mile rates** — loads dispatched the prior Tuesday (still on the old rate) plus loads dispatched Wednesday or later (on the new rate). The settlement worksheet accounts for both bands.
- The Wed 3pm CT settlement-week boundary doesn't itself change pay rates; the rate-change event is the Wednesday rate revision, applied to **new dispatches** from that point forward.
- The `RPM_GOAL_PAY_WINDOW_DAYS = 10` trailing window in the rate-per-mile cost-out captures roughly one-and-a-half rate weeks, smoothing the week-over-week rate change into a stable read while still tracking it fast enough to be current.

See `xfreight-owner-operator-program.md` § "Weekly rate revision" + "The dispatch date locks the rate" for full detail. The current week's rate is whatever was set on the most recent Wednesday; the published $1.89/mi reference is a recent baseline, not a fixed rate.
