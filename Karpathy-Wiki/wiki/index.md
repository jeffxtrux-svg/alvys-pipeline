---
title: Index
type: moc
tags: [index, map-of-content]
last_compiled: "2026-06-05"
---

# Wiki Index

The map of this knowledge base. Every compiled page is listed here, grouped by topic, with a one-line description. **Kept up to date automatically by the daily librarian pass** (see `/CLAUDE.md` rules). Last compiled: 2026-06-05.

## Meta

- [[About this wiki]] — what this wiki is, how it's fed, and how pages are compiled from `/raw`.

---

## Company Structure

- [[XFreight Entities]] — the five legal entities: X-Trux (carrier), X-Linx (broker), Truk-Way (leasing/payroll), and two future N&J entities.
- [[Truk-Way Leasing]] — equipment leasing, employer of W-2 staff, and owner-op group payment hub — three roles in one entity.
- [[Key People]] — JB Sweere (President), Jeff Hannahs (VP BD), Audra Newman (Safety/AP), Dan Heeren (Logistics), plus key external partners.

---

## Customers

- [[Customer Portfolio]] — all active, historical, and prospective customers with status notes.
- [[Billion Auto]] — dedicated 2-lane customer; rate agreement expired June 1, 2026 — renewal status unknown.
- [[AGCO RFP]] — 2026 truckload RFP (NOT AWARDED Jan 2026); bid structure and next-cycle lessons.
- [[JW Logistics]] — carrier relationship (X-Linx) with disputed history; hard-coded exclusion from all reports.

---

## Finance & KPIs

- [[Financial Performance]] — monthly goals, historical trend Aug 2024–Apr 2026, and 2026 YTD QB snapshot.
- [[Rate-Per-Mile Goal]] — live cost-out: driver pay $/mi + overhead $/mi ÷ operating ratio = goal rate; drives page-1 tiles.
- [[Cost Per Mile]] — itemized office-overhead breakdown (Jeff's "Jeff's Number" tab); currently pinned at $0.98/mi.
- [[Factoring]] — four vendors compared (Pathward, Triumph, OTR, eCapital); decision pending as of Oct 2025.
- [[Acrisure Dispute]] — active billing dispute with insurance broker; ~$95K claim vs ~$31K likely liability; unresolved as of June 2026.
- [[SBA 504 Financing]] — ~$3M real-estate+business purchase under evaluation; expected to bring N&J entities online.

---

## Safety & Compliance

- [[Safety Program]] — speed-over-limit rubric, coaching policy, MVR workflow, equipment inspections, and driver discipline framework.
- [[FMCSA CSA Scorecard]] — X-Trux carrier profile (DOT #841776 / MC #375851), BASIC percentile thresholds, page-10 rendering.
- [[Owner-Operator Program]] — $1.89/mi loaded+empty, no driver-facing cameras, no forced dispatch; hybrid direct-OO and OO-group structure.
- [[Driver Roster]] — Dec 2024 snapshot (21 drivers); settlement-week cycle (Wed 3pm CT); mileage target 2,750 mi/wk.

---

## Operations

- [[Brokerage X-Linx]] — X-Linx brokerage operations: co-broker (ABT), margin target (17.5%), revenue collapse 2024→2026.
- [[Daily Schedule]] — year-round Central wall-clock automation schedule; dual-cron + CT-hour-gate DST pattern.
- [[Daily Scorecard Email]] — 13-page daily executive brief: page-by-page breakdown, key constants, Bottom Line logic.

---

## Technology

- [[Data Pipeline Architecture]] — four-step pull→transform→write→upload skeleton; four source systems; no database.
- [[Power BI]] — reads `Alvys Master 2026.xlsx` from OneDrive; 200-column declarative schema; date-format constraints.
- [[OneDrive]] — pipeline staging layer; critical naming rule (`Alvys Master 2026.xlsx` vs `Alvys Pipeline.xlsx`); full folder map.
- [[QuickBooks Integration]] — five QB company files; refresh-token rotation; recursive JSON parser; AR aging buckets.
- [[Technology Stack]] — Alvys (TMS), Samsara (telematics), SambaSafety (MVR/CSA), Comdata (fuel), Highway.com (broker onboarding), and all other vendors.

---

## Decisions & Events

- [[Recent Decisions 2026-06-05]] — PRs #86–#93: driver Ack column, coaching policy, MVR window, fleet-miles MTD bug, MC # on page 10, AR tile layout fix, speed escalation Bottom Line, DST cron hardening, JB added as recipient.

---

### How to read this wiki

- Each entry is a `[[wikilink]]`; in Obsidian, click to open or hover to preview.
- Open the **graph view** in Obsidian to see how concepts connect.
- Pages cite their origin in a **Sources** section pointing back to `/raw`.
- See [[About this wiki]] for the full picture of how this is fed and compiled.
