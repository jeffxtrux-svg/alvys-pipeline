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

`SUM(Driver Rate) ÷ SUM(Total Dispatch Mileage)` for the **X-Trux asset fleet**
(Office slicer → X-Trux/XFreight; X-Linx and cancelled loads dropped), over a
**month-to-date window by default** — resets on the 1st of each month —
**settled loads only** (Driver Rate > 0). Set `RPM_GOAL_PAY_WINDOW_DAYS` to
force a fixed trailing-N-day window instead (e.g. `=10` restores the old
10-day behavior).

MTD is the default because it's how accounting reads the books — the cost/mile
on the brief lines up with monthly P&L conversations. On early-month days
when MTD is too sparse (<5 settled X-Trux loads or <5,000 miles), the read
widens through `RPM_GOAL_FALLBACK_WINDOWS` (30 / 60 / 90 days) and the brief
flags `pay_window_fallback=True`.

The **settled-only** filter matters whichever window is used: the freshest
loads have miles but $0 driver pay until they settle, and including them
would deflate the rate — so they're excluded until pay lands.

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

`goal = cost ÷ RPM_GOAL_TARGET_OR`. The **default is `0.95` — a 5% net margin**
on the fully-loaded cost (the target the business chose). Adjust the OR to change
the baked-in profit:

| `RPM_GOAL_TARGET_OR` | Net margin | Goal on a ~$3.05 current cost |
|----------------------|-----------|-------------------------------|
| `1.00` | 0% (break-even) | $3.05 |
| **`0.95`** | **5% (default)** | **$3.21** |
| `0.92` | 8% | $3.32 |
| `0.90` | 10% | $3.39 |
| `0.85` | 15% | $3.59 |

> Sample cost reflects today's pinned overhead (`$0.98/mi`) plus ~$2.05/mi driver
> pay. The cost number moves with the driver-pay leg every run; the table is here
> to show how the OR maps to a goal, not to lock a value.

> This margin is **net of total cost** (driver + overhead), which is *not* the
> same as the 30–36% *gross* margins in the manual goals worksheet — those are
> revenue minus driver pay only, before any office overhead.

## What shows on the brief

Four tiles plus a plain-language line that makes the number auditable from the
email itself:

- **Cost / mile · X-Trux** — the fully-loaded break-even (the headline).
- **Goal rate / mile** — cost ÷ OR; the pill reads "<x>% net · OR <r>" (5% by
  default), or "break-even · set profit %" if the OR is set back to 1.0.
- **Actual / mile · recent** — revenue ÷ miles over the same trailing window.
- **Gap to goal / mile** — green when actual ≥ goal, red when below.

The note also prints the **worksheet sanity check**: the office-cost-per-mile from
the manually kept `Goals and Trends.xlsx` (`RPM_GOAL_WORKSHEET_OVERHEAD`, default
`$0.88`) sits beside the live QB figure so the two can be compared at a glance.

Below the tiles, a **6-month trend** (`compute_rpm_goal_trend`) charts **cost /
goal / actual revenue per mile** by month so the goal reads as a living line — you
can see cost creep or a chronic actual-below-goal gap, not just today's snapshot.
The driver-pay leg varies by month; office overhead is **held flat at the current
YTD rate** (the QB P&L is a single fiscal-year report, so monthly overhead can't be
reconstructed). The cost/goal bars render only when the QB overhead leg is present;
the actual rev/mile bars always render.

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
| `RPM_GOAL_TARGET_OR` | `0.95` | Operating ratio the goal targets (0.95 = 5% net margin; 1.0 = break-even). |
| `RPM_GOAL_OVERHEAD_COMPANIES` | `X-Trux Inc,X-Linx Inc` | QB companies whose Total Expenses form the overhead pool. |
| `RPM_GOAL_OVERHEAD_ALLOC` | `1.0` | Fraction of the combined overhead the X-Trux miles absorb (1.0 = all; lower pushes some onto brokerage). |
| `RPM_GOAL_OVERHEAD_PIN` | `0.98` | **Hand-set override for the overhead leg.** Skips the live QB-derived calc and uses this dollar value instead. Set to `None` (or empty env var) to fall back to the live calculation. The live value is still computed and shown on the Data-check banner so you can watch the two converge. |
| `RPM_GOAL_INSURANCE_SURCHARGE` | `0.0` | Separate $/mi line added on top of overhead. **Zeroed in 2026** because the liability-insurance rate hike is already folded into `RPM_GOAL_OVERHEAD_PIN = 0.98`. Re-enable only if you decouple insurance from overhead again. |
| `RPM_GOAL_PAY_WINDOW_DAYS` | `10` | Trailing window (days) for the driver-pay-per-mile read; settled loads only. |
| `RPM_GOAL_WORKSHEET_OVERHEAD` | `0.88` | Manual office-cost-per-mile shown as a sanity check. |

### The overhead pin (`RPM_GOAL_OVERHEAD_PIN`)

While the QB-derived overhead leg is being validated against the books, the
brief uses a pinned value instead of the live calculation. The pin keeps the
goal stable through pulls that would otherwise read wrong overhead (e.g. a
late QB refresh, a company-name mismatch, or a near-empty Loads window that
inflates the per-mile cost).

- **Current value: `$0.98/mi`** — baseline overhead with the liability-insurance
  rate hike folded in. Bumped from `$0.92` when insurance was rolled in so the
  separate `RPM_GOAL_INSURANCE_SURCHARGE` line could be zeroed (no
  double-counting).
- **Live value still computed.** The brief's **Data check** banner prints both
  the pinned and live overheads side by side so the gap is visible. When the two
  converge for several runs, unpin (`RPM_GOAL_OVERHEAD_PIN = None`) and let the
  live calculation flow through.
- **Override per-run:** `RPM_GOAL_OVERHEAD_PIN=<value>` in `.env` or GitHub
  Secrets. Empty string = unpin.

### Fail-soft guards

The goal stays trustworthy on thin or bad data (constants in `src/scorecard_email.py`):

- **Min-sample window widening** — if the `RPM_GOAL_PAY_WINDOW_DAYS` window holds fewer
  than `RPM_GOAL_MIN_SETTLED_LOADS` (5) settled loads or `RPM_GOAL_MIN_WINDOW_MILES`
  (5,000) miles, the pay read widens through `RPM_GOAL_FALLBACK_WINDOWS` (30/60/90d)
  until it has a stable sample, and the brief's **Data check** banner notes the widening.
- **Plausibility band** — a cost/mi outside `RPM_GOAL_PLAUSIBLE_BAND` ($1.50–$5.00)
  flags the banner instead of reading as a trustworthy goal (usually a bad QB pull or
  a near-empty Loads window). Both checks live in `_rpm_goal_health`.

## Verify / debug

- **Offline cost-out (no network):** `python -m src.scorecard_email --check
  "Alvys Master 2026.xlsx"` prints the driver-pay leg, actual RPM, fiscal-YTD
  miles, and the target OR. (The office-overhead leg needs QuickBooks, so it shows
  `n/a` offline; the live email fills it in.)
- **Contract tests:** `python tests/test_rpm_goal.py` (or `pytest
  tests/test_rpm_goal.py`) lock the math — X-Linx/cancelled exclusion, the
  combined-overhead pool, the 5% default, break-even at OR 1.0, and OR layering.

## When you most commonly edit this

- **The goal reads blank / "pending QB cost-out":** the `QB_ProfitAndLoss.xlsx`
  wasn't readable this run, so the overhead leg is missing. The driver-pay leg and
  worksheet check still render. Confirm the QB refresh succeeded.
- **Overhead/mile looks wrong:** check the company names in
  `RPM_GOAL_OVERHEAD_COMPANIES` match the QB `Company` column, and that fiscal-YTD
  X-Trux miles are non-trivial (a near-empty Loads window inflates the per-mile cost).
- **Changing the profit target:** set `RPM_GOAL_TARGET_OR` (default `0.95` = 5%
  net; e.g. `0.92` for 8%, `0.90` for 10%, `1.0` for break-even) and the goal tile follows.
