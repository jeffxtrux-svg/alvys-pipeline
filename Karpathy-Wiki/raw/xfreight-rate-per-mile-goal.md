# XFreight rate-per-mile cost-out (seeded 2026-06-05 from repo)

> Source: `docs/knowledge-base/rate-per-mile-goal.md`, `src/scorecard_email.py`
> `compute_rpm_goal()`.

## What it is

A live, recomputed-every-run **cost / mile** number for X-Trux trucking, plus the **goal rate / mile** you should be quoting against. Replaces the old static $2.33 RPM goal with a number that self-corrects as the weekly owner-operator rate, the deadhead mix, and the monthly P&L move.

Shown on page 1 of the brief under the **"X-Trux Rate-per-Mile Goal · cost-out"** section. Four tiles + a 6-month trend chart.

## The formula

```
                  driver pay $/mi         office overhead $/mi
                  (live, trailing 10d)    (QB Total Expenses ÷ YTD miles, or pinned)
                          │                       │
cost / mile  =  ──────────┴───────────  +  ───────┴───────────
                                                          │
goal / mile  =                 cost / mile   ÷   target operating ratio
                                                  (1.0 = break-even; 0.95 = 5% net)
profit / mile =                goal / mile   −   cost / mile
```

## Leg 1 — driver/owner-op pay per mile (from Alvys, live)

`SUM(Driver Rate) ÷ SUM(Total Dispatch Mileage)` for the **X-Trux asset fleet** (Office slicer → X-Trux/XFreight; X-Linx and cancelled loads dropped), over a short trailing window (default **10 days**, `RPM_GOAL_PAY_WINDOW_DAYS`), **settled loads only** (Driver Rate > 0).

A short recent window — not year-to-date — is deliberate: the owner-op rate changes weekly. `Driver Rate` holds each load's full settled pay (base + accessorials), so a tight trailing read blends the current rate, accessorials, and deadhead into one honest $/mi.

The **settled-only filter** matters: the freshest loads have miles but $0 driver pay until they settle. Including them would deflate the rate.

**Fail-soft window widening:** if the 10-day window holds fewer than `RPM_GOAL_MIN_SETTLED_LOADS = 5` loads or `RPM_GOAL_MIN_WINDOW_MILES = 5000` miles, the read widens through `RPM_GOAL_FALLBACK_WINDOWS = (30, 60, 90)` days until it has a stable sample, and the brief's Data-check banner notes the widening.

## Leg 2 — office overhead per mile (from QuickBooks, currently PINNED)

**Today (pinned):** `RPM_GOAL_OVERHEAD_PIN = $0.98 / mile`. Hand-set while the live QB-derived calc is being validated against the books. Represents baseline overhead with the liability-insurance rate hike folded in (bumped from $0.92 to $0.98 when insurance was rolled into overhead instead of carried as a separate $0.07/mi line).

**Live calc (still computed, shown on Data-check banner side-by-side with the pin):** `(combined Total Expenses of RPM_GOAL_OVERHEAD_COMPANIES) ÷ (fiscal-YTD X-Trux miles)`. The companies are X-Trux Inc + X-Linx Inc — both share the same back office, so the goal pools both.

**Numerator companies:** `RPM_GOAL_OVERHEAD_COMPANIES = ("X-Trux Inc", "X-Linx Inc")`. Truk-Way Leasing and the N&J pair are NOT in the pool.

**Denominator:** fiscal-YTD X-Trux asset miles. The QB P&L is a "This Fiscal Year" report, so YTD miles keep numerator and denominator on the same period.

**100% of overhead lands on trucking miles** (`RPM_GOAL_OVERHEAD_ALLOC = 1.0`). Brokerage carries none — a deliberate choice that makes the X-Trux rate fully absorb the shared office cost. Brokerage is priced per load, not per mile, so per-mile overhead doesn't apply to it.

**Insurance surcharge zeroed.** `RPM_GOAL_INSURANCE_SURCHARGE = 0.0` because the $0.98 pin already absorbs the liability-insurance increase.

## Profit — layered on top via the operating ratio

`goal = cost ÷ RPM_GOAL_TARGET_OR`. Default `0.95` = 5% net margin on fully-loaded cost.

| `RPM_GOAL_TARGET_OR` | Net margin | Goal on a ~$3.05 cost |
|---|---|---|
| 1.00 | 0% (break-even) | $3.05 |
| **0.95** | **5% (default)** | **$3.21** |
| 0.92 | 8% | $3.32 |
| 0.90 | 10% | $3.39 |
| 0.85 | 15% | $3.59 |

This margin is **net of total cost** (driver + overhead), NOT the 30-36% gross margins from the manual goals worksheet (those are revenue minus driver pay only, before overhead).

## What shows on the brief

Four tiles on page 1:

- **Cost / mile · X-Trux** — fully-loaded break-even.
- **Goal rate / mile** — cost ÷ OR. Pill reads "<x>% net · OR <r>".
- **Actual / mile · recent** — revenue ÷ miles over the same trailing window.
- **Gap to goal / mile** — green when actual ≥ goal, red when below.

Below the tiles, a **6-month trend** (`compute_rpm_goal_trend`) charts cost / goal / actual revenue per mile by month. The driver-pay leg varies monthly; office overhead is held flat at the current YTD rate (QB P&L is a single fiscal-year report).

## Configuration

| Variable | Default | What it controls |
|---|---|---|
| `RPM_GOAL_TARGET_OR` | `0.95` | Operating ratio (0.95 = 5% net, 1.0 = break-even). |
| `RPM_GOAL_OVERHEAD_COMPANIES` | `("X-Trux Inc", "X-Linx Inc")` | QB companies whose Total Expenses form the overhead pool. |
| `RPM_GOAL_OVERHEAD_ALLOC` | `1.0` | Fraction of pooled overhead absorbed by X-Trux miles. |
| `RPM_GOAL_OVERHEAD_PIN` | `0.98` | Hand-set overhead $/mi override. Set to `None` (empty env var) to fall back to the live QB-derived calc. |
| `RPM_GOAL_INSURANCE_SURCHARGE` | `0.0` | Separate insurance $/mi line. Zeroed because folded into pin. |
| `RPM_GOAL_PAY_WINDOW_DAYS` | `10` | Trailing window for the driver-pay-per-mile read. |
| `RPM_GOAL_WORKSHEET_OVERHEAD` | `0.88` | Manual sanity-check value shown next to the QB figure. |

## When to unpin the overhead

The Data-check banner prints both the pinned `$0.98` and the live QB-derived overhead side-by-side. When the two converge for several consecutive runs, set `RPM_GOAL_OVERHEAD_PIN = None` (or empty the env var) and let the live calc flow through.

## Reconciliation with Jeff's manual worksheet

The owner's `Goals and Trends.xlsx` ("Jeff's Number" tab) already itemizes office cost per mile to **$0.85/mi (2025 YTD)** and **$0.88/mi (2026 YTD)** — wages, rent, insurance, lease, depreciation, interest, fees. With owner-op pay around $2.00–2.05 per total mile (the $1.81 base + accessorials, spread across ~7.5% deadhead), `$2.05 + $0.88 ≈ $2.93`. The pinned $0.98 is ~$0.10/mi above the worksheet because insurance was folded in.

The algorithm derives both legs from data rather than trusting those hand-entered cells.
