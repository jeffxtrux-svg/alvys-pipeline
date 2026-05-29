# X-Trux rate-per-mile goal (the "cost-out")

> **In one sentence:** the daily brief rebuilds, from live data every run, what it
> actually costs to run one X-Trux mile — driver pay **plus** a fair share of the
> office overhead — and turns that into a rate-per-mile goal to quote against.

This replaces the old static `$2.33` RPM goal (and the by-hand `~$2.92` cost
estimate) with a number that **re-costs the operation on every refresh**, so it
self-corrects as the weekly owner-operator rate, the deadhead mix, and the
monthly P&L move. It lives on **page 1** of the executive brief under the
**"X-Trux Rate-per-Mile Goal · cost-out"** section, and is computed by
`compute_rpm_goal()` in `src/scorecard_email.py`.

## Why it exists

X-Trux is the **asset trucking** company that pays owner-operators by the mile
($1.81/mi base today, + $40/extra stop, + detention, + layover). To know what to
charge, we need the *fully-loaded* cost of a mile, not just the driver pay. The
old goal under-counted because it never folded the back-office overhead into the
per-mile number — which is exactly why it read low. X-Linx (brokerage) is priced
per load, not per mile, so it is **excluded from the rate** — but its office
overhead is still **absorbed by the trucking miles** (see below).

## The formula

```
                  driver/owner-op pay $/mi        office overhead $/mi
                  (live, trailing window)         (QB Total Expenses ÷ YTD miles)
                          │                                │
cost / mile  =  ──────────┴──────────────  +  ─────────────┴──────────────
                                                                  │
goal / mile  =                 cost / mile   ÷   target operating ratio
                                                  (1.0 = break-even; 0.90 = 10% net …)
profit / mile =                goal / mile   −   cost / mile
```

### Leg 1 — driver/owner-op pay per mile  *(from Alvys, live)*

`SUM(Loads[Driver Rate]) ÷ SUM(Loads[Total Dispatch Mileage])` for the **X-Trux
asset fleet** (Office slicer → X-Trux/XFreight; X-Linx and cancelled loads
dropped), over a **trailing window** (default 90 days, `RPM_GOAL_PAY_WINDOW_DAYS`).

A recent window — not year-to-date — is deliberate: `Driver Rate` already holds
each load's full settled pay (base + accessorials), so a trailing read blends the
**current** weekly rate, accessorials, and deadhead into one honest $/mi and
tracks rate changes within a few weeks instead of dragging a stale annual average.

### Leg 2 — office overhead per mile  *(from QuickBooks, monthly)*

`(combined Total Expenses of the configured companies) ÷ (fiscal-YTD X-Trux miles)`.

- **Numerator:** `RPM_GOAL_OVERHEAD_COMPANIES` (default **X-Trux Inc + X-Linx
  Inc**) — the two companies share one back office, so the goal pools both. Read
  from the `QB_ProfitAndLoss.xlsx` the pipeline already stages (the `opex` /
  "Total Expenses" line per company in `compute_qb_pnl`). Truk-Way Leasing and the
  N&J pair are **not** in the pool.
- **Denominator:** fiscal-YTD X-Trux asset miles. The QB P&L is a *This Fiscal
  Year* report, so YTD miles keep numerator and denominator on the same period.
- **All overhead lands on the trucking miles.** Brokerage carries none — a
  deliberate choice that makes the X-Trux rate fully absorb the shared office cost.

### Profit — layered on top via the operating ratio

`goal = cost ÷ RPM_GOAL_TARGET_OR`. The **default is `1.0` (break-even, no profit
baked in)** — the cost number is the deliverable first; the profit target is set
*after* the true cost is known. Set the OR below 1.0 to bake in net margin:

| `RPM_GOAL_TARGET_OR` | Net margin | Goal on a $2.92 cost |
|----------------------|-----------|----------------------|
| `1.00` | 0% (break-even) | $2.92 |
| `0.95` | 5%  | $3.07 |
| `0.90` | 10% | $3.24 |
| `0.85` | 15% | $3.44 |

> This margin is **net of total cost** (driver + overhead), which is *not* the
> same as the 30–36% *gross* margins in the manual goals worksheet — those are
> revenue minus driver pay only, before any office overhead.

## What shows on the brief

Four tiles plus a plain-language line that makes the number auditable from the
email itself:

- **Cost / mile · X-Trux** — the fully-loaded break-even (the headline).
- **Goal rate / mile** — cost ÷ OR; the pill says "break-even · set profit %" until
  a target margin is configured, otherwise "<x>% net · OR <r>".
- **Actual / mile · recent** — revenue ÷ miles over the same trailing window.
- **Gap to goal / mile** — green when actual ≥ goal, red when below.

The note also prints the **worksheet sanity check**: the office-cost-per-mile from
the manually kept `Goals and Trends.xlsx` (`RPM_GOAL_WORKSHEET_OVERHEAD`, default
`$0.88`) sits beside the live QB figure so the two can be compared at a glance.

## Reconciling the ~$2.92 estimate

The owner's `Goals and Trends.xlsx` ("Jeff's Number" tab) already itemizes office
cost per mile — wages, rent, liability/cargo/trailer insurance, lease payments,
depreciation, interest, truck fees/tolls, professional fees — to **$0.85/mi (2025
YTD)** and **$0.88/mi (2026 YTD)**. With owner-operator pay around **$2.00–2.05**
per *total* mile (the $1.81 base + accessorials, spread across ~7.5% deadhead),
`$2.05 + $0.88 ≈ $2.93`, matching the $2.92 working estimate. The algorithm
derives both legs from data rather than trusting those hand-entered cells.

## Configuration

All optional; defaults live in `src/scorecard_email.py` and are documented in
`.env.example`:

| Variable | Default | What it controls |
|----------|---------|------------------|
| `RPM_GOAL_TARGET_OR` | `1.0` | Operating ratio the goal targets (1.0 = break-even). |
| `RPM_GOAL_OVERHEAD_COMPANIES` | `X-Trux Inc,X-Linx Inc` | QB companies whose Total Expenses form the overhead pool. |
| `RPM_GOAL_PAY_WINDOW_DAYS` | `90` | Trailing window for the driver-pay-per-mile read. |
| `RPM_GOAL_WORKSHEET_OVERHEAD` | `0.88` | Manual office-cost-per-mile shown as a sanity check. |

## Verify / debug

- **Offline cost-out (no network):** `python -m src.scorecard_email --check
  "Alvys Master 2026.xlsx"` prints the driver-pay leg, actual RPM, fiscal-YTD
  miles, and the target OR. (The office-overhead leg needs QuickBooks, so it shows
  `n/a` offline; the live email fills it in.)
- **Contract tests:** `python tests/test_rpm_goal.py` (or `pytest
  tests/test_rpm_goal.py`) lock the math — X-Linx/cancelled exclusion, the
  combined-overhead pool, break-even default, and the profit-via-OR layering.

## When you most commonly edit this

- **The goal reads blank / "pending QB cost-out":** the `QB_ProfitAndLoss.xlsx`
  wasn't readable this run, so the overhead leg is missing. The driver-pay leg and
  worksheet check still render. Confirm the QB refresh succeeded.
- **Overhead/mile looks wrong:** check the company names in
  `RPM_GOAL_OVERHEAD_COMPANIES` match the QB `Company` column, and that fiscal-YTD
  X-Trux miles are non-trivial (a near-empty Loads window inflates the per-mile cost).
- **Ready to set a profit target:** set `RPM_GOAL_TARGET_OR` (e.g. `0.90`) and the
  goal tile flips from "break-even · set profit %" to the margin-loaded rate.
