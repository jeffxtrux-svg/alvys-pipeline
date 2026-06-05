---
title: Daily Scorecard Email
type: concept
tags: [reporting, email, brief, scorecard]
sources: ["raw/xfreight-daily-scorecard-email.md", "raw/xfreight-daily-operations-reports.md"]
related: ["[[Data Pipeline Architecture]]", "[[Daily Schedule]]", "[[Safety Program]]", "[[Financial Performance]]", "[[Rate-Per-Mile Goal]]", "[[FMCSA CSA Scorecard]]"]
---

# Daily Scorecard Email

The 13-page daily executive brief sent at 5:00am Central to jeff@xfreight.net + jb@xfreight.net. Rendered as a PDF by WeasyPrint and sent via Microsoft Graph. Read-only: it reads staged OneDrive files, pulls nothing from source APIs.

## Summary

A 13-page PDF scoped to **X-Trux + X-Linx** (JW Logistics excluded throughout). Covers overview P&L and KPIs, safety compliance (pages 2–6), fleet operations (pages 7–9), FMCSA CSA scorecard (page 10), and AR/QB accounting (pages 11–13). Recipients: jeff@xfreight.net + jb@xfreight.net (jb added 2026-06-05, PR #93).

## Key Ideas

- Read-only job — reads `Alvys Master 2026.xlsx` + QB `.xlsx` files + `Samsara_Master.xlsx` + `SambaSafety_Master.xlsx`. Emails the PDF.
- Same-day idempotency marker in OneDrive prevents double-emailing across the 5 backup cron slots.
- Manual `workflow_dispatch` bypasses the same-day marker so on-demand resends actually send.
- Failure notice email fired by `if: failure()` step — so a broken morning is noticed.

## Page Structure (4 Sections, 13 Pages)

### Page 1: Overview

The executive summary. Contains:

| Element | Content |
|---|---|
| **Bottom Line** | Auto-generated narrative (`scorecard_insights.bottom_line()`). Names STOP/sit-down speed escalations (excluding improvers), trailers overdue on 120-day policy, AR/margin/RPM gaps. |
| **Entity P&L** | X-Trux + X-Linx revenue, margin, miles, loads (MTD + trend). |
| **AR / AP trend tiles** | 6-month balance trend mini-charts. |
| **AR tiles** | 5 buckets (Current / 1–30 / 31–60 / 61–90 / 91+) in a nested 5-col table (fits inside the fixed 4-col outer layout). |
| **QB-vs-Alvys AR reconciliation** | Variance + 61+ spot-check. |
| **Safety tiles** | 24h / 7d / MTD safety events + HOS violations + DVIR defects. |
| **6-month safety trend** | Monthly bar chart. |
| **X-Trux Rate-Per-Mile Goal** | [[Rate-Per-Mile Goal]] cost-out. 4 tiles + 6-month trend. |
| **Safety event detail tables** | Last 7 days: HOS violations, safety events (with driver **Ack** column), DVIR defects, Coaching needs assigned. |

### SAFETY Section (Pages 2–6)

| Page | Builder | Content |
|---|---|---|
| 2 | `build_page9` | Driver compliance — SambaSafety MVR, license status, DOT medical card expiry (Alvys Drivers). |
| 3 | `build_page2` | Safety & compliance detail — last 24h events, HOS violations, DVIR defects, coaching. |
| 4 | `build_page2b` | Per-driver Samsara safety scores — Speed-Over-Limit % (6mo/3mo/MTD) + comment + trend. |
| 5 | `build_page_equipment(kind='tractors')` | Equipment compliance — tractor DOT inspections (365d federal + 120d company). |
| 6 | `build_page_equipment(kind='trailers')` | Equipment compliance — trailer inspections (same policy). |

### OPERATIONAL Section (Pages 7–9)

| Page | Builder | Content |
|---|---|---|
| 7 | `build_page4` | Driver mileage by settlement week. 5 weeks (Wed 3pm CT cycle). Below-target tile: `DRIVER_TARGET_MILES = 2750`. |
| 8 | `build_page_fleet` | Fleet operations — best/worst 5 trucks MTD by MPG. Fleet miles · MTD tile. |
| 9 | `build_page_idle` | Fleet idle — all trucks ranked by avg idle/wk over 5 settlement weeks. Idle %, idle gallons (`idle_hours × 0.8 gph`), MPG. |

### CSA SCORECARD Section (Page 10)

| Page | Builder | Content |
|---|---|---|
| 10 | `build_csa_scorecard_page` | FMCSA BASIC percentile ranks for X-Trux (DOT #841776). INTERVENTION LIKELY flags at FMCSA thresholds. Fails soft if CSV absent. See [[FMCSA CSA Scorecard]]. |

### ACCOUNTING Section (Pages 11–13)

| Page | Builder | Content |
|---|---|---|
| 11 | `build_page_ar_accounting` | QB AR overdue (31+) + Alvys un-invoiced loads + 90+ collections. |
| 12 | `build_page7` | QB-vs-Alvys reconciliation by customer (`compute_ar_customer_reconciliation`). Rows sum to page-1 variance. |
| 13 | `build_page8` | Bill-by-bill matching (`compute_bill_reconciliation`). Alvys invoice # / Load # vs QB `Num` (`_norm_inv` strips leading "T"). |

## Key Constants

| Constant | Value | Description |
|---|---|---|
| `COACH_EVENT_THRESHOLD` | 2 | Drivers with ≥ 2 events in window need coaching |
| `DRIVER_TARGET_MILES` | 2750 | Weekly miles target |
| `VIOLATION_WINDOW_DAYS` | 90 | MVR violation lookback (page 2 + page-1 tile) |
| `LICENSE_EXPIRY_WARN_DAYS` | 60 | License expiring-soon window |
| `SAMBA_HIGH_RISK_SCORE` | 16 | Fallback MVR high-risk threshold |
| `RPM_GOAL_TARGET_OR` | 0.95 | Operating ratio for RPM goal (5% net) |
| `RPM_GOAL_OVERHEAD_PIN` | $0.98 | Pinned overhead $/mi |
| `XLINX_MARGIN_GOAL` | 17.5% | X-Linx brokerage margin target |
| `MEDICAL_EXPIRY_WARN_DAYS` | 30 | DOT medical card warning window |
| `DRIVER_EXPIRY_CRITICAL_DAYS` | 14 | DOT medical card critical window |
| `SETTLEMENT_WEEKS` | 5 | Settlement weeks shown on pages 7 + 9 |
| `_ACK_KEEP_DAYS` | 3 | Days to keep signed coaching on list |

## Bottom Line Escalation Logic

The Bottom Line paragraph (`scorecard_insights.bottom_line()`) can include:

- `STOP-THIS-DRIVER speed escalations (pg 4): NAME (X% peak, MTD Y%)` — ≥ 3.0% and NOT showing improvement.
- `Sit-down conversations needed on speed (pg 4): NAME (X% peak, MTD Y%)` — ≥ 2.5% and NOT improving.
- Trailer overdue on 120-day policy — named units (up to 8 + "+N more").
- AR / margin / RPM gaps if thresholds exceeded.

The same `compute_speed_comment` function drives both the Bottom Line and page 4 — they cannot disagree.

## Workflow Mechanics

- **Scheduled:** `0 10 UTC` primary (5am CDT) + four backup retries.
- **Idempotency:** Reads a same-day marker in OneDrive at startup; exits clean if today's brief already sent.
- **Failure notice:** Sent to jeff@ + jb@ from `if: failure()` step.
- **Manual dispatch:** Bypasses same-day marker.

## Connections

- [[Data Pipeline Architecture]] — the four upstream jobs this reads from.
- [[Daily Schedule]] — when it runs and the DST pattern.
- [[Safety Program]] — pages 2–6 + 10.
- [[Rate-Per-Mile Goal]] — page-1 cost-out tiles.
- [[FMCSA CSA Scorecard]] — page 10.
- [[Financial Performance]] — entity P&L tiles.
- [[OneDrive]] — reads `Alvys Master 2026.xlsx` + QB files + Samsara/SambaSafety masters.
- [[JW Logistics]] — excluded from all tiles and reconciliation pages.

## Sources

- `raw/xfreight-daily-scorecard-email.md`
- `raw/xfreight-daily-operations-reports.md`
