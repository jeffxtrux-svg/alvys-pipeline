---
title: Employee Responsibilities
type: concept
tags: [people, org, accountability, briefs, operations, safety, finance]
sources: ["raw/xfreight-employee-responsibilities.md"]
related: ["[[Key People]]", "[[Daily Scorecard Email]]", "[[Safety Program]]", "[[Brokerage X-Linx]]", "[[Risk Register]]", "[[Playbook — Driver Disciplinary]]"]
---

# Employee Responsibilities

The canonical accountability map for XFreight. Every playbook `owner:` field, risk-register `owner:` field, and brief-routing decision should reference this page. Seeded 2026-06-14 from the role-focused brief delivery decision.

## Accountability Map

| Person(s) | Owns | Receives (primary) | CC on |
|---|---|---|---|
| **Audra** | Safety + Compliance · invoice closeout (loads invoiced timely + carrier invoices entered into Alvys) | Safety & Compliance brief (daily) | — |
| **Jackson + Dan** | On-time delivery · truck coverage / return loads · drivers hitting 2,750 mi/wk average · driver dispatching · maintenance on trailers + Truk-Way tractors · overall brokerage (X-Linx) operations | Operational / Maintenance brief (daily) | — |
| **Jeff + JB** | Accounting / financial · sales · recruiting | Accounting / Financial brief (daily); Sales brief (weekly, Jeff primary); Recruiting brief (weekly, Jeff primary) | All non-owned briefs (governance visibility) |
| **Dan + JB + Jeff** | Consolidated executive view | Executive brief (X-Trux + X-Linx, daily) | — |

## Brief Routing (Canonical)

Every brief routes to its owner(s) first, with Jeff + JB cc'd unless they're already the primary.

| Brief | Recipients | Status |
|---|---|---|
| **Executive brief** (`scorecard_email.py`) | Dan, JB, Jeff | Live |
| **Safety & Compliance brief** (`safety_compliance_email.py`) | Audra (primary); Jeff, JB cc | Built — in jeff-only test mode; flip to canonical distribution when ready |
| **Operational / Maintenance brief** | Jackson, Dan (primary); Jeff, JB cc | Not yet built |
| **Accounting / Financial brief** | Jeff, JB | Not yet built |
| **Sales brief** (weekly) | Jeff (primary); JB cc | Not yet built |
| **Recruiting brief** (weekly) | Jeff (primary); JB cc | Not yet built |

## Responsibility Detail

### Audra — Safety, Compliance, Invoice Closeout

- All safety events, HOS violations, DVIR defects, coaching workflow.
- Driver MVR + license + medical-card monitoring (SambaSafety + Alvys Drivers sheet).
- DOT inspection scheduling for trucks + trailers (120d company policy; see [[Safety Program]] for the 120d/365d distinction). All inspection costs paid by X-Trux Inc.
- **Invoice closeout** — every delivered load invoiced timely (customer side) + every carrier invoice entered into Alvys (brokered side). Slippage drags AR aging and Power BI accuracy.

### Jackson + Dan — Operations, Maintenance, Brokerage Ops

- **On-time delivery** — every load delivered within the customer's appointment window.
- **Truck coverage / return loads** — every truck has a return load back to a productive region.
- **Driver mileage target** — average **2,750 miles/week** per driver.
- **Driver dispatching** — load assignment, route planning, driver communication in transit.
- **Maintenance — trailers** — all trailers across the fleet: scheduling, condition, replacement decisions.
- **Maintenance — Truk-Way tractors** — the leased-out tractor fleet; coordination with OO-group drivers.
- **Overall X-Linx brokerage operations** — day-to-day brokerage execution (booking, carrier search, carrier rate negotiation, in-transit tracking, carrier escalations). Strategic brokerage BD stays with Jeff + JB.
- Coordinates with Audra on DOT inspection scheduling (Audra owns the 120d compliance angle; Jackson + Dan own the broader maintenance program).

### Jeff + JB — Finance, Sales, Recruiting

- All accounting / financial decisions: P&L, AR collections, [[Factoring]] partner, cost-out, RPM goal, capital decisions.
- All sales: customer relationships at VP+ level, RFP pricing, contract negotiations, customer escalations beyond dispatch level.
- All recruiting: hiring decisions, OO-group lease decisions, separations.
- JB has signoff on: rate concessions >5%, separations, factoring switches, contracts >$200K/yr, capital expansion.
- Jeff leads day-to-day BD execution.

### Dan + JB + Jeff — Consolidated Leadership

- Receive the executive brief so operational and financial pictures stay aligned.
- JB + Jeff are cc'd on every role-specific brief for governance — they observe but don't action those items day-to-day.

## Tractor Inspection — Split Ownership

*X-Trux* (owner-operator) tractors: Audra's safety + compliance lane solely.
*Truk-Way* fleet tractors: **shared** — Audra (safety/CSA Maintenance BASIC) **plus** Jackson + Dan (maintenance program). Until the Trucks sheet carries `Truck.Fleet.Name`, action items on Audra's brief can't be split per-fleet; the action's `owner` label calls out the shared piece explicitly.

Trailer inspections: Jackson + Dan only. Audra's brief filters trailers out of the equipment action item.

## Cadence Summary

- **Daily** (5am CT): Executive, Safety & Compliance, Operational / Maintenance, Accounting / Financial.
- **Weekly** (Monday morning): Sales pipeline, Recruiting pipeline.
- All briefs use the DST-proof dual-cron + CT-hour-gate pattern. See [[Daily Schedule]].

## Related Decision

The role-focused brief delivery model was decided 2026-06-14 — see [[Decision Journal]] for rationale, assumptions, and predicted outcome.

## Connections

- [[Key People]] — bios and contact details for each person listed.
- [[Daily Scorecard Email]] — the existing executive brief (13 pages, Dan + JB + Jeff).
- [[Safety Program]] — Audra's domain detail.
- [[Brokerage X-Linx]] — Jackson + Dan's brokerage execution domain.
- [[Daily Schedule]] — when each brief fires.

## Sources

- `raw/xfreight-employee-responsibilities.md`
