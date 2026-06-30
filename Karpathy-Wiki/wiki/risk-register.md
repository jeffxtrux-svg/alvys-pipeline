---
title: Risk Register
type: register
tags: [risk, compliance, finance, operations, decision-support]
sources: ["raw/xfreight-risk-register.md"]
related: ["[[Decision Journal]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Acrisure Dispute]]", "[[Active Disputes and Open Issues]]", "[[Customer Portfolio]]", "[[Factoring]]", "[[Data Pipeline Architecture]]", "[[SBA 504 Financing]]"]
last_reviewed: "2026-06-30"
---

# Risk Register

A living list of XFreight's open business risks — ranked by severity, each with its exposure, what's being done, and the **watch signal** that means it's getting worse. This is decision-support, not a status report: the goal is to keep the handful of things that could actually hurt the business in front of leadership, and to let the brief flag them automatically when they cross a line.

> **How this page works.** The librarian keeps this current from new material in `/raw` (daily briefs, notes). Add a risk by appending to `raw/xfreight-risk-register.md`; update severity/status as things change; close a risk by setting its status to `closed` and moving it to the archive at the bottom. Each entry follows `templates/risk.md`. **Seeded 2026-06-13 — severities, owners, and dollar exposures need Jeff's review.**

## At a glance

| Risk | Severity | Status | Owner | Watch signal |
|------|:--------:|:------:|-------|--------------|
| Equipment inspection backlog | **High** | Open | Safety / Logistics | Any unit past due (brief flags red) |
| CSA BASIC near intervention | **High** | Monitor | Safety | A BASIC ≥ its 65th/80th threshold |
| Rate-per-mile goal may be light | Medium | Watch | Jeff | Live cost/mi creeping above the $0.98 goal pin |
| Customer concentration | Medium | Watch | Jeff (BD) | One customer > ~25% of revenue |
| Factoring onboarding (Triumph) | Medium | Improving | JB / Jeff | Onboarding ~6/16–17, then cash-flow relief |
| SambaSafety CSV fragility | Medium | Mitigated | Pipeline | CSV age > 60h |
| Manual Alvys upload dependency | Medium | Open | Ops | File age > 30h |
| Pipeline cron fragility | Medium | Mitigated | Pipeline | A morning with no brief by ~7am CT |
| AR aging / collections | Medium | Ongoing | AP / AR | 90+ AR rising |

---

## High severity

### Equipment inspection backlog
**What it is.** As of 2026-06-13 the fleet carries **4 tractors and 13 trailers** past due on the federal 365-day annual inspection. **Exposure:** roadside out-of-service orders, a climbing FMCSA Maintenance BASIC, lost truck utilization. **Mitigation:** the [[Daily Scorecard Email]] Equipment Compliance pages now flag past-due units in red. **Watch:** any unit past due. **Owner:** Audra (Safety) + Dan (Logistics). See [[Safety Program]], [[FMCSA CSA Scorecard]].

### CSA BASIC near intervention
**What it is.** FMCSA flags intervention when a BASIC crosses the 65th percentile (Unsafe Driving, Crash Indicator) or 80th (all others). Tracked on brief page 10 from the SambaSafety CSA scorecard. **Exposure:** intervention, audit, higher insurance cost. **Watch:** any BASIC crossing its threshold. **Owner:** Audra. See [[FMCSA CSA Scorecard]], [[Safety Program]].

---

## Medium severity

### Rate-per-mile goal may be light
**What it is.** The $0.08–0.10/mi insurance increase may exceed what the cost-out absorbed — the overhead pin moved $0.92→$0.98 (~$0.06/mi), ~$0.02–0.04/mi less than the stated increase. If so, the [[Rate-Per-Mile Goal]] is set a touch below true cost (under-pricing). **Mitigation:** Jeff asked to monitor the costing and **alert on evidence we're light**. **Watch:** actual all-in cost per mile creeping above the $0.98 goal pin; insurance expense per mile (QB) vs what the pin assumes. **Owner:** Jeff. See [[Decision Journal]].

### Customer concentration
**What it is.** Revenue may be concentrated in a few customers. **Action:** quantify each customer's share of X-Trux + X-Linx revenue from Alvys (the data exists — a good first analysis). **Exposure:** losing one large account materially hits revenue. **Watch:** any single customer above ~25% of revenue. **Owner:** Jeff (BD). See [[Customer Portfolio]].

### SambaSafety CSV fragility
**What it is.** The SambaSafety API token expired 2026-06-02; the feed is now CSV-drop only via Power Automate. **Exposure:** if the drop stops, driver MVR/license compliance and CSA data go **stale silently**. **Mitigation:** hourly-armed refresh + the Data Refresh Status page. **Watch:** CSV age > 60h. **Owner:** pipeline. See [[Data Pipeline Architecture]], [[Safety Program]]. Paired decision: [[Decision Journal]] (retire SambaSafety API).

### Manual Alvys upload dependency
**What it is.** The daily afternoon manual upload of `Alvys Master2026.xlsx` feeds revenue and P&L for both the brief and Power BI. Single human dependency; no API yet. **Exposure:** a missed upload silently stales the numbers. **Mitigation:** Data Refresh Status page flags staleness. **Watch:** file age > 30h. **Owner:** ops. See [[Data Pipeline Architecture]].

### Pipeline cron fragility
**What it is.** GitHub's scheduled cron is best-effort and has dropped whole morning batches (e.g., 2026-06-08). **Exposure:** no brief / stale dashboards on drop mornings. **Mitigation:** dual-cron DST hardening, staggered backups, 6am healthchecks, and an off-GitHub Cloudflare Worker backstop. **Watch:** a morning with no brief by ~7am CT. **Owner:** pipeline. See [[Data Pipeline Architecture]], [[Daily Scorecard Email]].

### Factoring onboarding (Triumph)
**What it is.** **Triumph** selected for invoice factoring; onboarding expected **~June 16–17, 2026** to relieve cash flow. Onboarding required clearing the existing operating loan — funded by a **$40K owner capital injection ($20K Jeff + $20K JB)** plus a **trailer refinance** to cover the gap. **Exposure (residual):** onboarding execution this week; factoring fees (~1%); new trailer-refi debt service. **Watch:** onboarding completes on schedule, then AR aging should shorten. **Owner:** JB / Jeff. See [[Factoring]], [[Financial Performance]].

### AR aging / collections
**What it is.** Overdue AR (31+/90+) and the QB-vs-Alvys variance from un-invoiced loads are tracked on the accounting pages. **Exposure:** cash flow and factoring penalties. **Watch:** 90+ AR rising. **Owner:** Audra (AP/AR). See [[Daily Scorecard Email]], [[Factoring]].

---

## Archive (closed risks)

### Acrisure renewal + billing dispute — CLOSED (2026-05-01 / 2026-06-13)
The 2026 insurance renewal went through May 1, 2026 (+~$0.08–0.10/mi, absorbed into the cost-out). The back-billing reconciliation was **negotiated to $18,000, paid, and resolved** (2026-06-13) — near Jeff's floor, well under the ~$95K ask and ~$31K mid-estimate. Closed 2026-06-30. **Residual watch:** the higher premium is a permanent margin drag; shop alternative broker/carrier before the next renewal cycle. That forward-looking item rolls into the "Rate-per-mile goal may be light" watch. See [[Acrisure Dispute]], [[Insurance and Banking]].

### Billion Auto contract — RENEWED (June 2026)
The dedicated rate agreement **renewed** — both the Rapid City and Mason City lanes maintained, plus a **fuel surcharge added for protection**. Was the portfolio's most immediate revenue risk; now secured. See [[Billion Auto]].

### SBA 504 financing — SHELVED (2026-06-13)
**Not currently on the table** (Jeff, 2026-06-13); removed from the active list. Context retained in [[SBA 504 Financing]] if it returns.
