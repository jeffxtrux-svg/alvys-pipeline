---
title: DOT Inspection Policy
type: concept
tags: [safety, compliance, equipment, dot, fmcsa, policy]
sources: ["raw/xfreight-dot-inspection-policy.md"]
related: ["[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Playbook — Equipment Inspection Backlog]]", "[[Risk Register]]", "[[Daily Scorecard Email]]"]
---

# DOT Inspection Policy

XFreight (X-Trux Inc) runs a **120-day company inspection policy** — voluntarily stricter than the federal 365-day annual requirement. These two windows show up as separate pills on the brief's Equipment Compliance pages (pages 5–6) and must be kept distinct in all labels, playbooks, and risk entries.

## Summary

There are two inspection windows in play. The federal rule (365 days) defines what is legally out of service. XFreight's own policy (120 days) is the operational deadline — it fires at the 4-month mark and drives the inspection-scheduling cadence. By the time a unit crosses the company 120-day threshold, it is still ~245 days away from the federal out-of-service limit.

## The Two Windows

| Window | Length | What "OVERDUE" means | In-service? |
|---|---|---|---|
| **120-day company policy** | 120 days from last DOT inspection | Flagged — needs inspection scheduled. | **Yes — still legal to run.** |
| **365-day federal annual** | 365 days from last DOT inspection | Out of service per FMCSA. | **No — must not operate.** |

A unit must be **245+ days past the company 120-day policy** (365 − 120 = 245) before it crosses the federal 365-day limit. Under normal operations, units are inspected well within weeks of the 120-day flag — so federal out-of-service status is essentially never reached.

## Why XFreight Runs the Tighter Policy

1. **Driver safety** — catching wear, brake/tire issues, and electrical problems at 4 months prevents in-service failures and DOT roadside out-of-service orders.
2. **Equipment longevity** — earlier intervention on small problems beats cascading repairs after 12 months of additional wear.
3. **CSA Maintenance BASIC** — every roadside inspection defect raises the FMCSA Maintenance BASIC percentile. The 120-day policy keeps the score lower than running to the federal limit would.
4. **Operational headroom** — units flagged at 120 days can be scheduled between dispatches, not pulled mid-route.

## Who Pays

**X-Trux Inc covers all DOT inspection costs** for every piece of equipment, regardless of which entity holds title and regardless of whether a trailer is pulled by a company driver or an owner-operator. The cost lives on the X-Trux P&L as maintenance overhead.

## How the Brief Renders This

The Equipment Compliance pages (page 5 tractors, page 6 trailers) show **two** summary pills with distinct meaning:

- **"Annual inspection (365d federal):"** — counts units past the federal 365-day window. Should almost always read "All current" given the 120-day company policy keeps everything well ahead of the federal line.
- **"DOT inspection (120d policy):"** — counts units past the company 120-day policy. This is the one that lights up and drives scheduling. "X OVERDUE" here means X units need inspection per company policy — **not** that they are out of service.

The per-unit "DAYS" column shows days remaining or past on the **120-day company policy** by default, since that is the operational deadline.

## Language Rules (KB + Code)

When writing about inspection status anywhere:

- **"Past due" / "OVERDUE" / red badge** — must state which window. Default to "flagged as needing inspection (120d company policy)" unless the text explicitly cites the 365d federal rule. Units past only the company policy remain **in service**.
- **"Out of service"** — reserved language. Use only for units past the federal 365-day limit (i.e., 245+ days past the company 120-day threshold). Do **not** say "out of service per company policy" or "out of service per FMCSA" for units past only the 120-day threshold.
- The Equipment Inspection Backlog risk entry and its playbook track the **120-day company policy** backlog, not federal-DOT-overdue equipment.

## Connections

- [[Safety Program]] — broader safety compliance context; Audra Newman owns the program.
- [[Playbook — Equipment Inspection Backlog]] — the response protocol when units cross the 120-day threshold.
- [[Risk Register]] — "Equipment inspection backlog" entry (High severity, Open status) tracks 120-day policy violations.
- [[FMCSA CSA Scorecard]] — DOT roadside inspection defects affect the Maintenance BASIC percentile.
- [[Daily Scorecard Email]] — Equipment Compliance pages 5 and 6.

## Sources

- `raw/xfreight-dot-inspection-policy.md` — canon clarification (2026-06-14).
