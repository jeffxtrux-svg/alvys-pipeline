---
title: Index
type: moc
tags: [index, map-of-content]
last_compiled: "2026-06-19"
---

# Wiki Index

The map of this knowledge base. Every compiled page is listed here, grouped by topic, with a one-line description. **Kept up to date automatically by the daily librarian pass** (see `/CLAUDE.md` rules). Last compiled: 2026-06-19.

## Meta

- [[About this wiki]] — what this wiki is, how it's fed, and how pages are compiled from `/raw`.

---

## Decision Support

- [[Risk Register]] — living list of open business risks, ranked by severity, each with its exposure, mitigation, and the watch signal that means it's getting worse. Machine-readable companion: `wiki/risk-signals.yml` (read by the brief's Risk Watch strip).
- [[Decision Journal]] — consequential decisions logged with rationale, assumptions, and predicted outcome, then graded later — so you can tell judgment from luck. Companions: `wiki/decision-outcomes.yml` (predictions) + `wiki/decision-grades.json` (live grading state, written by the brief each run).
- **Predictions & Lessons (Phase 2D)** — Group A of the KB roadmap, shipped 2026-06-19:
  - `wiki/jb-mtd-forecasts.yml` — JB's monthly MTD-landing forecasts, auto-graded against actuals by `src/forecast_grader.py`. Brief surfaces a "Forecast Accuracy" chip on page 1 (silent until first forecast is graded).
  - `wiki/weekly-retros.yml` — Friday qualitative log: surprised-by / worked / didn't-work / lessons. Brief surfaces the most recent retro on page 1 as "This Week's Lessons." `.github/workflows/weekly_retro_draft.yml` auto-opens a PR every Friday 4pm CT with a pre-populated draft.
  - `src/retro_pattern_detector.py` — scans the retros file for lessons recurring across 2+ weeks within 90 days; renders a "Recurring Patterns" panel on the brief (silent until enough retros exist).
- [[Recent Decisions 2026-06-05]] — changelog of pipeline/code changes and the rationale behind each (distinct from the business Decision Journal).

---

## Operating Playbooks

Codified response patterns — "what to do when X happens." Each playbook has a concrete trigger, a step-by-step protocol, decision points, escalation paths, and an append-only run log. Triggered by signals in the daily brief or by operator judgment; outcomes feed back into the [[Risk Register]] and [[Decision Journal]].

- [[Playbook — Customer Escalation]] — when a customer relationship is at risk; save the account if savable, exit cleanly if not.
- [[Playbook — Driver Disciplinary]] — coaching through separation, with the FMCSA/insurance documentation trail intact.
- [[Playbook — AR Follow-up]] — 30 / 60 / 90+ day collections cycle tied to the brief's AR aging tile.
- [[Playbook — RFP Response]] — competitive bidding process built on the AGCO 2026 lessons.
- [[Playbook — Factoring Partner Switch]] — change providers without breaking cash flow.
- [[Playbook — Equipment Inspection Backlog]] — response to past-due tractor/trailer inspections flagged on the brief.

### Safety Accountability Playbooks

Per-category response guides for the 9 accountability items surfaced in the Teams morning Adaptive Cards and the daily safety brief. Each playbook covers the regulation, the FMCSA consequence, the exact decision tree (1st Coach → 2nd Verbal → 3rd Written → 4th+ Escalate), literal action scripts, documentation requirements, and escalation paths. Source: `raw/xfreight-accountability-playbooks.md`.

- [[Playbook — HOS Violation]] — Hours of Service violation (49 CFR Part 395); HOS Compliance BASIC (80th percentile); standard 4-tier warning ladder; roadside OOS enters at Level 3+. Owner: Audra.
- [[Playbook — DVIR Defect]] — DVIR defect logged by driver (49 CFR Part 396.11/396.13); equipment-focused response (repair + sign-off before dispatch); discipline only if unit dispatched with known unrepaired defect. Owner: Audra + ops.
- [[Playbook — Coaching Needed]] — Driver has 2+ unacknowledged Samsara safety events or open coaching session not closed; 14-day unacked = Level 1 trigger; ack derived from SafetyEvents `coachingStatus`, not CoachingSessions. Owner: Audra.
- [[Playbook — DOT Inspection — Tractors]] — Tractor OVERDUE on 120-day company policy (not the 365-day federal limit); equipment scheduling action; Audra schedules, Dan+Jackson coordinate Truk-Way dispatch; X-Trux pays. Owner: Audra (+ Dan/Jackson for Truk-Way).
- [[Playbook — DOT Inspection — Trailers]] — Trailer OVERDUE on 120-day company policy; Logistics-owned (Dan+Jackson); Audra's brief filters trailers out of her action items. Owner: Dan + Jackson.
- [[Playbook — DVIR Compliance]] — Missing DVIR (driver did not submit required inspection report); 49 CFR Part 396.11; driver behavior failure, not equipment defect; standard 4-tier warning ladder. Owner: Audra.
- [[Playbook — Prior Day Logs]] — Uncertified ELD logs (driver did not sign prior-day log within 24h per 49 CFR Part 395.8); HOS Compliance BASIC (80th percentile); standard 4-tier warning ladder. Owner: Audra.
- [[Playbook — Low Safety Score]] — Samsara composite safety score below threshold; pattern indicator across all event types; CSA Unsafe Driving BASIC (65th percentile — most sensitive BASIC); standard 4-tier warning ladder. Owner: Audra.
- [[Playbook — Speeding]] — Time-over-posted-limit % (49 CFR Part 392.6); CSA Unsafe Driving BASIC (65th percentile); non-linear entry (>=3% enters at Level 2 minimum); Bottom Line two-week = automatic Level 2. Owner: Audra.

---

## Company Structure

- [[XFreight Entities]] — the five legal entities: X-Trux (carrier), X-Linx (broker), Truk-Way (leasing/payroll), and two future N&J entities.
- [[Carrier Identity]] — DOT #841776 / MC #375851 for X-Trux; why these are hardcoded in the pipeline; fleet-size caveat on the FMCSA AvgPowerUnits field.
- [[Truk-Way Leasing]] — equipment leasing, employer of W-2 staff, and owner-op group payment hub — three roles in one entity.
- [[Key People]] — JB Sweere (President), Jeff Hannahs (VP BD), Audra Newman (Safety/AP), Dan Heeren (Logistics), plus key external partners.
- [[Employee Responsibilities]] — canonical accountability map: who owns what, which briefs each person receives, and how to route playbook/risk `owner:` fields.
- [[Contact Directory]] — office address, banking, insurance, factoring vendor contacts, major customer contacts, and technology vendors.

---

## Customers

- [[Customer Portfolio]] — all active, historical, and prospective customers with status notes.
- [[Billion Auto]] — dedicated 2-lane customer; rate agreement renewed June 2026 (both lanes + FSC added).
- [[AGCO RFP]] — 2026 truckload RFP (NOT AWARDED Jan 2026); bid structure and next-cycle lessons.
- [[JW Logistics]] — carrier relationship (X-Linx) with disputed history; hard-coded exclusion from all reports.
- `wiki/customers/_README.md` — per-customer pattern-page directory (new 2026-06-19). Documents the schema for living entity pages that accumulate history / patterns / what's-worked over time. Existing customer pages at the flat wiki root keep their location; the brief's entity-context lookup matches both.

---

## Per-Driver Pattern Pages

New 2026-06-19 (Phase 2E / Group B). Living one-page-per-driver files capturing what we know about each — coaching history, recurring issues, what's worked / hasn't. Append-only history sections accumulate into pattern material the AI can reference when the driver surfaces in today's data.

- `wiki/drivers/_README.md` — directory README + page template + creation criteria.
- [[Michael Hall]] — X-Trux owner-operator with chronic ~2.5% speed-over-limit pattern; "Need to sit down with this driver" brief comment tier (seed).
- [[Lacey Campbell]] — X-Trux driver with multi-category breadth (3.6% speed + CDL + license + MVR + risk flag); unusual cross-category pattern (seed).

---

## Finance & KPIs

- [[Financial Performance]] — monthly goals, historical trend Aug 2024–Apr 2026, and 2026 YTD QB snapshot.
- [[Rate-Per-Mile Goal]] — live cost-out: driver pay $/mi + overhead $/mi ÷ operating ratio = goal rate; drives page-1 tiles.
- [[Cost Per Mile]] — itemized office-overhead breakdown (Jeff's "Jeff's Number" tab); currently pinned at $0.98/mi.
- [[Factoring]] — four vendors compared (Pathward, Triumph, OTR, eCapital); Triumph selected June 2026, onboarding ~6/16–17.
- [[Acrisure Dispute]] — billing dispute with insurance broker; RESOLVED at $18,000 paid (2026-06-13), well under the ~$95K ask.
- [[Insurance and Banking]] — insurance program (Acrisure/Great West), historical broker, banking (First Dakota NB), and entity IDs.
- [[SBA 504 Financing]] — ~$3M real-estate+business purchase under evaluation; shelved as of 2026-06-13.
- [[Active Disputes and Open Issues]] — consolidated watch list: Acrisure resolved, Billion Auto renewed, JWL, AGCO, X-Linx collapse, fleet shrinkage.
- **Market Context (Phase 2E)** — `wiki/market-context.json` (managed by `src/market_context.py` + `.github/workflows/market_context_refresh.yml`, weekly Monday 6pm CT). Pulls U.S. retail diesel from FRED (series GASDESW); brief renders a "Market Context · US Diesel" chip on page 1 with current price + WoW + YoY change. Silent until the workflow has fired at least once.

---

## Safety & Compliance

- [[Safety Program]] — speed-over-limit rubric, coaching policy, MVR workflow, equipment inspections, and driver discipline framework.
- [[Progressive Discipline Policy]] — formal 5-level discipline structure (drafted 2026-06-16, pending JB sign-off): two tracks (OO vs. Truk-Way employee), Samsara speed-flag triggers, 14-day coaching-backlog trigger, CSA escalation rules, immediate-termination grounds.
- [[DOT Inspection Policy]] — 120-day company policy vs. 365-day federal annual: what each window means, who pays, and the language rules for "overdue" vs "out of service."
- [[Driver Discipline and Incidents]] — written-warning framework, documented incidents (Brad/chafed-brake-hose), Sharefile record structure, and the pipeline's current coverage gap on historic incidents.
- [[Coaching Ack]] — June 6, 2026 fix: coaching ack now derived from SafetyEvents `coachingStatus`, not the always-empty CoachingSessions sheet.
- [[FMCSA CSA Scorecard]] — X-Trux carrier profile (DOT #841776 / MC #375851), BASIC percentile thresholds, page-10 rendering.
- [[Owner-Operator Program]] — $1.89/mi loaded+empty, no driver-facing cameras, no forced dispatch; hybrid direct-OO and OO-group structure.
- [[Driver Roster]] — Dec 2024 snapshot (21 drivers); settlement-week cycle (Wed 3pm CT); mileage target 2,750 mi/wk.
- [[Settlement Week]] — Wed 3pm CT week boundary; dispatch date locks the per-mile rate; where it appears on the brief (pages 7 and 9).

---

## Operations

- [[Brokerage X-Linx]] — X-Linx brokerage operations: co-broker (ABT), margin target (17.5%), revenue collapse 2024→2026.
- [[Daily Schedule]] — year-round Central wall-clock automation schedule; dual-cron + CT-hour-gate DST pattern; updated to 2h cadence.
- [[Refresh Cadence]] — source-data pulls bumped from 3x/day to every 2 hours (4am–6pm CT) in June 2026; rationale and cost.
- [[Daily Scorecard Email]] — 13-page daily executive brief: page-by-page breakdown, key constants, Bottom Line logic.
- [[Daily Operations]] — day-to-day operating rhythm: three email cadences, escalation patterns, full phone directory, fuel spend.
- [[Brief Roadmap]] — current brief stack (Executive, Safety, Financial, MTD upload) and what is planned (Operations brief); page-placement rules by audience.
- [[Jeff JB Tracking Philosophy]] — Jeff (facts-first / lagging) vs. JB (forecast-first / leading): two mental models that coexist; implications for any brief or report design.
- [[Dan Tracking Driver Connection]] — Dan's facts-first + skeptical tracking style, plus his deep driver connections and sponsorship of the planned per-driver report.
- [[OTD Early Warning Wishlist]] — planned new brief page: trucks projected late today; data sources, scoping decisions, and build sequence (not yet built).
- [[Driver Report Wishlist]] — planned per-driver weekly snapshot going directly to drivers; first non-management brief audience (not yet built).
- [[Audra Safety Brief Day 1]] — pre-observation hypothesis of Audra's morning workflow with the Safety brief (first fire 2026-06-16); questions to verify after Day 3–5.
- [[Slack / Teams Morning Digest]] — Phase 3A compact morning channel post: MTD KPIs + Risk Watch + Decisions Graded; setup and data sources.
- [[X-Trux Open-Trip Rule]] — loads with any trip in Open status are excluded from the entity P&L until every leg progresses past Open (replaces the "Driver Rate > 0" proxy).

---

## Technology

- [[Data Pipeline Architecture]] — four-step pull→transform→write→upload skeleton; four source systems; no database.
- [[Power BI]] — reads `Alvys Master 2026.xlsx` from OneDrive; 200-column declarative schema; date-format constraints.
- [[OneDrive]] — pipeline staging layer; critical naming rule (`Alvys Master 2026.xlsx` vs `Alvys Pipeline.xlsx`); full folder map.
- [[QuickBooks Integration]] — five QB company files; refresh-token rotation; recursive JSON parser; AR aging buckets.
- [[Technology Stack]] — Alvys (TMS), Samsara (telematics), SambaSafety (MVR/CSA), Comdata (fuel), Highway.com (broker onboarding), and all other vendors.

---

## Decisions & Events

- [[Recent Decisions 2026-06-05]] — PRs #86–#97 (June 5–6): driver Ack, coaching policy, MVR window, fleet-miles MTD bug, MC # on page 10, AR tile layout, speed escalation, DST cron, JB as recipient, dispatch-date-locks-rate rule, and the June 6 coaching-ack fix.

---

### How to read this wiki

- Each entry is a `[[wikilink]]`; in Obsidian, click to open or hover to preview.
- Open the **graph view** in Obsidian to see how concepts connect.
- Pages cite their origin in a **Sources** section pointing back to `/raw`.
- See [[About this wiki]] for the full picture of how this is fed and compiled.
