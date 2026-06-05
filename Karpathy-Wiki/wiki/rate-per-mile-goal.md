---
title: Rate-Per-Mile Goal
type: concept
tags: [kpi, finance, cost-out, rpm]
sources: ["raw/xfreight-rate-per-mile-goal.md", "raw/xfreight-cost-per-mile-breakdown.md"]
related: ["[[Financial Performance]]", "[[Cost Per Mile]]", "[[XFreight Entities]]", "[[Daily Scorecard Email]]"]
---

# Rate-Per-Mile Goal

The live, recomputed-every-run cost-out for X-Trux trucking. Replaces the old static $2.33 RPM goal with a number that self-corrects as the owner-operator rate, deadhead mix, and monthly P&L move. Shown on page 1 of the [[Daily Scorecard Email]].

## Summary

`cost/mile = driver pay/mi (live, trailing 10d) + office overhead/mi (pinned at $0.98 or live from QB)`. `goal/mile = cost/mile ÷ operating ratio (default 0.95 = 5% net)`. Four tiles on page 1 show cost, goal, actual, and gap. The gap is green when actual revenue/mi ≥ goal.

## Key Ideas

- **Two-legged formula:** driver-pay leg (live, short window) + overhead leg (currently pinned).
- **Pinned overhead: $0.98/mi.** Will be unpinned when the live QB-derived calc converges for several consecutive runs.
- **Default OR: 0.95** (5% net). Increasing OR lowers the goal rate; decreasing it raises the bar.
- **All X-Trux overhead + X-Linx overhead lands on X-Trux miles** (brokerage is per-load, not per-mile).
- **Fail-soft window widening:** if fewer than 5 settled loads or <5,000 miles in the 10-day window, the read expands to 30 / 60 / 90 days automatically.

## Formula

```
driver pay $/mi   =  SUM(Driver Rate) ÷ SUM(Total Dispatch Mileage)
                      [X-Trux asset fleet, settled loads only, trailing 10d]

overhead $/mi     =  RPM_GOAL_OVERHEAD_PIN  (currently $0.98)
                   OR (live)  (X-Trux + X-Linx Total Expenses YTD) ÷ (X-Trux miles YTD)

cost / mile       =  driver pay + overhead

goal / mile       =  cost ÷ RPM_GOAL_TARGET_OR

profit / mile     =  goal − cost
```

## Configuration Constants

| Variable | Default | Meaning |
|---|---|---|
| `RPM_GOAL_TARGET_OR` | `0.95` | Operating ratio; 0.95 = 5% net margin on fully-loaded cost |
| `RPM_GOAL_OVERHEAD_COMPANIES` | `("X-Trux Inc", "X-Linx Inc")` | QB companies in the overhead pool |
| `RPM_GOAL_OVERHEAD_ALLOC` | `1.0` | 100% of pooled overhead to X-Trux miles |
| `RPM_GOAL_OVERHEAD_PIN` | `$0.98` | Hand-set override; set to `None` to use live QB calc |
| `RPM_GOAL_INSURANCE_SURCHARGE` | `$0.00` | Zeroed — insurance folded into pin |
| `RPM_GOAL_PAY_WINDOW_DAYS` | `10` | Trailing days for driver-pay read |
| `RPM_GOAL_WORKSHEET_OVERHEAD` | `$0.88` | Sanity-check value from Jeff's worksheet |
| `RPM_GOAL_MIN_SETTLED_LOADS` | `5` | Minimum loads for stable sample |
| `RPM_GOAL_FALLBACK_WINDOWS` | `(30, 60, 90)` | Widening fallback sequence if window is thin |

## What Shows on Page 1

Four tiles:
1. **Cost / mile · X-Trux** — fully-loaded break-even.
2. **Goal rate / mile** — cost ÷ OR. Sub-pill shows "X% net · OR Y".
3. **Actual / mile · recent** — revenue ÷ miles in the same trailing window.
4. **Gap to goal / mile** — green when actual ≥ goal; red when below.

Plus a **6-month trend** chart (`compute_rpm_goal_trend`) showing cost / goal / actual revenue per mile by month.

## Operating Ratio Sensitivity

| `RPM_GOAL_TARGET_OR` | Net margin | Goal on ~$3.05 cost |
|---|---|---|
| 1.00 | 0% (break-even) | $3.05 |
| **0.95** | **5% (default)** | **$3.21** |
| 0.92 | 8% | $3.32 |
| 0.90 | 10% | $3.39 |
| 0.85 | 15% | $3.59 |

## Why the Overhead Is Pinned

The live QB-derived overhead ($0.80/mi as of Apr 2026) is lower than the $0.98 pin because the pin buffers:
- The 2026 liability-insurance rate hike (~$0.07–0.10/mi absorbed).
- Lower-mile months spreading fixed costs over fewer miles (~$0.05–0.08/mi).
- Truk-Way intercompany allocations.

When the Data-check banner shows the live figure converging with $0.98 for several consecutive runs, set `RPM_GOAL_OVERHEAD_PIN = None` (or empty the env var).

## Historical Context

Before the current system:
- `RPM_GOAL_OVERHEAD_PIN = $0.92` + `RPM_GOAL_INSURANCE_SURCHARGE = $0.07` = $0.99/mi.
- Changed to `$0.98 + $0.00` when the liability-insurance increase was folded into the overhead pin.

Jeff's manual worksheet ("Jeff's Number" tab in Goals and Trends.xlsx) gives overhead at **$0.78/mi (2025 actual)** and **$0.80/mi (2026 YTD)**. The pin at $0.98 is ~$0.18 above the worksheet — the buffer is intentional.

## Reconciliation with Driver Pay

Owner-op rate per the [[Owner-Operator Program]]: $1.89/mi loaded + empty. Spread across ~7.5% deadhead:
- Effective rate ≈ $1.89/mi × (1 + 0.075 deadhead fraction) ≈ $2.03–2.05/mi.
- Add $0.98 overhead → break-even ~$3.01–3.03/mi.
- Goal at OR 0.95: ~$3.17–3.19/mi.

## Connections

- [[Cost Per Mile]] — the detailed overhead itemization (Jeff's Number tab).
- [[Financial Performance]] — actual RPM vs. goal by month.
- [[Daily Scorecard Email]] — page 1 tiles + 6-month trend.
- [[Owner-Operator Program]] — the driver-pay leg ($1.89/mi rate).
- [[XFreight Entities]] — why both X-Trux and X-Linx are in the overhead pool.

## Sources

- `raw/xfreight-rate-per-mile-goal.md` — formula, constants, methodology.
- `raw/xfreight-cost-per-mile-breakdown.md` — itemized overhead data.
