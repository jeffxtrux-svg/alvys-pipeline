# XFreight Risk Register — seed (2026-06-13)

Source-of-record for the compiled `wiki/risk-register.md`. Initial set seeded by
Claude from known operating context (the data pipeline, the daily brief, the
existing wiki pages). **Severities, owners, and dollar exposures need Jeff's
review** — these are starting estimates, not validated figures. Add new risks
by appending here; the librarian compiles this into the wiki register.

## High severity

- **Equipment inspection backlog.** As of 2026-06-13 the fleet is carrying 4
  tractors and 13 trailers past due on the federal 365-day annual inspection.
  Exposure: roadside out-of-service orders, FMCSA Maintenance BASIC percentile
  climb, lost truck utilization. Mitigation: the brief's Equipment Compliance
  pages now flag past-due units in red; Safety/Logistics to schedule. Watch:
  any unit past due. Owner: Audra (Safety) + Dan (Logistics).

- **CSA BASIC percentiles near intervention.** FMCSA flags intervention when a
  BASIC crosses 65th percentile (Unsafe Driving, Crash Indicator) or 80th (all
  others). Tracked on brief page 10 from the SambaSafety CSA scorecard. Exposure:
  intervention, audit, insurance cost. Watch: any BASIC crossing its threshold.
  Owner: Audra.

- **Acrisure insurance dispute.** Open dispute with the insurance broker (detail
  in the Acrisure Dispute wiki page). Exposure: coverage/premium/billing and
  management time. Watch: unresolved past the next policy renewal. Owner: JB / Jeff.

## Medium severity

- **Customer concentration.** Revenue may be concentrated in a few customers.
  Action: quantify each customer's share of X-Trux + X-Linx revenue from Alvys
  (data exists). Exposure: losing one large account materially hits revenue.
  Watch: any single customer above ~25% of revenue. Owner: Jeff (BD).

- **Billion Auto contract lapsed.** The Billion Auto dedicated 2-lane rate
  agreement expired June 1, 2026; renewal status unknown. Exposure: a known,
  recurring revenue stream at risk. Watch: still unrenewed. Owner: Jeff (BD).

- **SambaSafety CSV-drop fragility.** The SambaSafety API token expired
  2026-06-02; the feed is now CSV-drop only via Power Automate. Exposure: if the
  drop stops, driver MVR/license compliance and CSA data go stale silently.
  Mitigation: hourly-armed refresh + the Data Refresh Status page. Watch: CSV age
  > 60h. Owner: pipeline.

- **Manual Alvys Master upload dependency.** The daily afternoon manual upload of
  `Alvys Master2026.xlsx` feeds revenue and P&L for both the brief and Power BI.
  Single human dependency; no API yet. Exposure: a missed upload silently stales
  the numbers. Mitigation: Data Refresh Status page flags staleness. Watch: file
  age > 30h. Owner: ops.

- **Pipeline / GitHub Actions cron fragility.** GitHub's scheduled cron is
  best-effort and has dropped whole morning batches (e.g., 2026-06-08). Exposure:
  no brief / stale dashboards on drop mornings. Mitigation: dual-cron DST
  hardening, staggered backups, 6am healthchecks, an off-GitHub Cloudflare Worker
  backstop. Watch: a morning with no brief by ~7am CT. Owner: pipeline.

- **Factoring cost / cash-flow reliance.** Working capital depends on factoring;
  the vendor decision is still open (Pathward / Triumph / OTR / eCapital).
  Exposure: factoring fees erode margin; AR aging into penalty bands. Watch: AR
  aging trend, factoring fee as a % of revenue. Owner: JB / Jeff.

- **AR aging / collections.** Overdue AR (31+/90+) and the QB-vs-Alvys variance
  from un-invoiced loads are tracked on the accounting pages. Exposure: cash flow
  and factoring penalties. Watch: 90+ AR rising. Owner: Audra (AP/AR).

- **SBA 504 financing execution.** SBA 504 financing is in flight. Exposure:
  timeline and rate slippage on a financing the plan depends on. Watch: milestone
  or rate movement. Owner: JB / Jeff.
