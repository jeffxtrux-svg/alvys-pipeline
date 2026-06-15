# XFreight Risk Register — seed (2026-06-13)

Source-of-record for the compiled `wiki/risk-register.md`. Initial set seeded by
Claude from known operating context (the data pipeline, the daily brief, the
existing wiki pages). **Severities, owners, and dollar exposures need Jeff's
review** — these are starting estimates, not validated figures. Add new risks
by appending here; the librarian compiles this into the wiki register.

## High severity

- **Equipment inspection backlog.** As of 2026-06-13 the fleet is carrying 4
  tractors and 13 trailers **flagged as needing inspection** under the
  **120-day company policy** (corrected 2026-06-14 — the prior wording said
  "federal 365-day annual" which was wrong). Flagged units remain in service
  while scheduling; the federal 365-day rule is the boundary that would
  actually take a unit out of service, and XFreight's 120d policy keeps the
  fleet well ahead of it.
  See `xfreight-dot-inspection-policy.md` for the canon distinction between the
  120d company policy and the 365d federal rule. Exposure: drift toward the
  federal 365d limit (would require 245+ days past company policy), worsening
  Maintenance BASIC if a roadside inspection finds a defect, lost truck
  utilization once units are pulled for inspection. Mitigation: the brief's
  Equipment Compliance pages show both pills (120d company policy and 365d
  federal) so the operator can tell at a glance which threshold has been
  crossed; Safety/Logistics schedules from the 120d list. Watch: any unit past
  the 120d company policy. Owner: Audra (Safety) + Dan (Logistics). DOT
  inspections covered by X-Trux Inc for all equipment.

- **CSA BASIC percentiles near intervention.** FMCSA flags intervention when a
  BASIC crosses 65th percentile (Unsafe Driving, Crash Indicator) or 80th (all
  others). Tracked on brief page 10 from the SambaSafety CSA scorecard. Exposure:
  intervention, audit, insurance cost. Watch: any BASIC crossing its threshold.
  Owner: Audra.

- **Insurance — Acrisure renewal & cost** (severity downgraded High→Medium, 2026-06-13).
  The 2026 renewal went through May 1, 2026 with a ~$0.08–0.10/mi premium increase,
  already absorbed into the cost-out. The separate ~$95K billing reconciliation
  (~$31K likely) is still to settle. Forward: evaluate an alternative broker/carrier
  before the next renewal — a different option may be needed down the road. Verify
  the overhead pin ($0.92→$0.98 ≈ $0.06/mi) fully reflects the $0.08–0.10/mi increase.
  Owner: JB / Jeff.

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

## Updates (2026-06-13, afternoon — Jeff)

- **Acrisure billing reconciliation RESOLVED:** negotiated to **$18,000, paid**. Near Jeff's floor, well under the ~$95K ask. Renewal (May 1) + billing both closed; residual is the cost-watch only. → archive the Acrisure risk.
- **Billion Auto contract RENEWED:** both Rapid City + Mason City lanes maintained, **fuel surcharge added** for protection. → remove "Billion Auto contract lapsed" from active risks (secured/archive).
- **Factoring:** **Triumph selected**; onboarding ~June 16–17, 2026. Required paying off the operating loan — funded by **$40K owner capital ($20K Jeff + $20K JB) + a trailer refinance**. → reframe factoring risk as "onboarding (Triumph), improving."
- **SBA 504: SHELVED** — not currently on the table. → remove from active risks.
- **NEW watch — rate-per-mile goal may be light:** the $0.08–0.10/mi insurance increase may exceed the ~$0.06/mi the pin absorbed ($0.92→$0.98). Jeff: **monitor the costing and alert on evidence we're light on the goal.** Watch actual cost/mi vs the $0.98 pin.
