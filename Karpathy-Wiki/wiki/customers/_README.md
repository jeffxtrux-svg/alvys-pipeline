---
title: Customers — Per-Entity Pattern Pages
type: register
tags: [customers, patterns, ai-context]
last_reviewed: "2026-06-19"
---

# Per-Customer Pattern Pages

A directory of one-page-per-customer files. Same intent as the [[Drivers]] directory but for customer relationships — captures what the AI knows about each customer so when their name surfaces in AR, in a dispute, in an RFP, the brief / AI has context instead of treating each event as novel.

For continuity, **existing customer wiki pages live at the flat root of `wiki/`** (e.g., [[Billion Auto]], [[JW Logistics]], [[Customer Portfolio]]) — those pre-date this directory and stay where they are. New per-customer pages can go either at the root or here, depending on whether they're "current portfolio" or pattern-focused. The brief's entity-context lookup matches both locations.

## When to create or update a page

- Customer has a recurring issue (slow pay, lane changes, RFP cycle, dispute pattern)
- Customer relationship has a named history dimension worth preserving (e.g., AGCO 2026 RFP loss — see [[AGCO RFP]])
- Customer is in the top 10 by revenue or is mission-critical to a single entity's P&L
- Customer relationship has a person-to-person dimension (Jeff knows the buyer personally, JB knows the AP contact, etc.)

## Page template

See `templates/customer.md` (copy + edit). Minimum useful content:

- **At a glance** — entity served (X-Trux / X-Linx), monthly revenue, primary contact, lane(s)
- **Patterns** — what we keep seeing (slow pay, lane volume seasonality, RFP cycle, etc.)
- **What's worked** — sales angles, pricing structures, service tactics that landed
- **What hasn't worked** — same for things that didn't
- **Open** — current open items (disputes, RFPs in flight, AR aging)
- **History** — append-only log of consequential events (RFP wins/losses, lane changes, escalations)

## Existing customer pages (flat naming, pre-2026-06-19)

- [[Billion Auto]] — $47K/month dedicated lanes (Rapid City + Mason City), FSC added 2026 renewal
- [[JW Logistics]] — excluded from brief KPIs per portfolio rules; see [[JW Logistics Exclusion]]
- [[AGCO RFP]] — 2026 RFP loss, lessons captured
- [[Acrisure Dispute]] — vendor not customer, but follows the same per-entity pattern (insurance broker)
- [[Customer Portfolio]] — portfolio overview
- [[Customers Additional]] — smaller / additional accounts

## Connections

- [[Customer Portfolio]] — portfolio-level overview
- [[Playbook — Customer Escalation]] — response protocol when a customer page is triggered
- [[Playbook — RFP Response]] — RFP-cycle protocol
- [[Playbook — AR Follow-up]] — slow-pay protocol
- [[Decision Journal]] — RFP-bid and contract-renewal decisions
