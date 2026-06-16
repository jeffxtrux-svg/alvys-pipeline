---
title: Index
type: moc
tags: [index, map-of-content]
last_compiled: "2026-06-16"
---

# Wiki Index

The map of this knowledge base. Every compiled page is listed here, grouped by topic, with a one-line description. **Kept up to date automatically by the daily librarian pass** (see `/CLAUDE.md` rules). Last compiled: 2026-06-16.

## Meta

- [[About this wiki]] — what this wiki is, how it's fed, and how pages are compiled from `/raw`.

---

## Decision Support

- [[Risk Register]] — living list of open business risks, ranked by severity, each with its exposure, mitigation, and the watch signal that means it's getting worse.
- [[Decision Journal]] — consequential decisions logged with rationale, assumptions, and predicted outcome, then graded later — so you can tell judgment from luck.
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

---

## Safety & Compliance

- [[Safety Program]] — speed-over-limit rubric, coaching policy, MVR workflow, equipment inspections, and driver discipline framework.
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
