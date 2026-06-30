---
title: Playbook — RFP Response
type: playbook
tags: [playbook, sales, customers, rfp, pricing, bd]
status: active
owner: Jeff Hannahs
last_revised: "2026-06-14"
trigger: "Existing customer or prospect sends a rate-bid packet; dedicated lane up for re-bid"
sources: ["raw/xfreight-playbook-rfp-response.md"]
related: ["[[AGCO RFP]]", "[[Customer Portfolio]]", "[[Rate-Per-Mile Goal]]", "[[Brokerage X-Linx]]", "[[Decision Journal]]", "[[Risk Register]]"]
---

# Playbook — RFP Response

Competitive bidding process. Built on the AGCO 2026 lessons — bid lanes we can actually run profitably; don't lose the relationship trying to win at a price that hurts.

## Trigger — When to Run

- An existing customer sends an annual RFP packet (typically Q4 or early Q1 for the calendar year ahead).
- A prospect invites XFreight into a bid (cold or warm).
- An existing dedicated lane is up for re-bid mid-year.

## Goal

Submit a competitive, profitable bid that XFreight can actually execute — or cleanly decline so we don't burn the relationship for next year.

## Pre-Checks

1. Read the RFP packet end-to-end: lanes, volumes, accessorial terms, payment terms, service requirements, technology requirements (EDI, tracking visibility), and bid-back deadline.
2. Check current AR aging with this customer — outstanding AR is a flag.
3. Confirm whether we have the equipment and driver capacity for the requested volume.
4. Pull historical rates run with this customer (Alvys load history) to anchor pricing.

## Steps

1. **Day 1 — log and gate** — Jeff logs the RFP in the active opportunities list, sets a calendar reminder for deadline minus 5 days. Initial read: "can we do this at all?" Pass to step 2 if yes; branch to decline if no.
2. **Lane-by-lane costing** — for each lane: estimated total miles (loaded + empty), driver pay/mi (current OO rate), fuel cost at current diesel, accessorials. Add target margin: X-Trux 25% / X-Linx 17.5% / negotiable for one-off lanes.
3. **Volume realism check** — Dan reviews: can we cover the requested loads/wk with current capacity? If not, do we add equipment for this account or bid lower volume?
4. **Pricing strategy** — Jeff + JB: bid to win or bid to hold the seat? **AGCO 2026 lesson:** do not bid significantly below cost to win a multi-lane RFP — they award on price and the unprofitable lanes hurt for a year.
5. **Submit by deadline minus 2 days** — never submit on the last day; allows time for clarification questions from the customer.
6. **Track award outcome** — even on losses, ask for the awarded rate by lane (some shippers share). Log in the customer file.

## Decision Points

- **If our cost-out shows negative margin at the implied market rate** — do not bid that lane. Bid the lanes that work, decline the rest with a one-line note.
- **If the customer is currently 60+ days past due** — Jeff + JB before bidding; AR risk may outweigh new revenue.
- **If the RFP requires EDI/tracking integrations we don't have** — scope the cost of building or buying, include in the bid, or decline with reason.
- **If the customer is strategic (large existing or pipeline prospect)** — JB may approve a thinner margin to hold the seat.

## Escalation

- **JB** for any bid total >$500K/year of revenue OR any sub-target margin bid.
- **Outside finance review** for any bid requiring capacity expansion (>5 truck additions).

## Capture

- Append outcome to this playbook's run log (customer, RFP year, lanes bid, lanes won, $/year, margin %).
- **If we lost** — capture the awarded rate (if known) vs our bid as a [[Decision Journal]] entry: too high, too low, or right but lost on other criteria?
- **If we won** — set a 90-day post-award review reminder: are the lanes performing to bid assumptions?
- If a recurring pattern emerges (losing every multi-lane RFP), add to [[Risk Register]] and revisit pricing strategy.

## Connections

- [[AGCO RFP]] — 2026 not-awarded case study; the lessons that seeded this playbook.
- [[Rate-Per-Mile Goal]] — the cost-out anchor for lane pricing.
- [[Customer Portfolio]] — update pipeline status when an RFP is won or lost.
- [[Decision Journal]] — loss post-mortems and margin-trade decisions belong here.
- [[Risk Register]] — bid-strategy pattern failures go here if recurring.

## Sources

- `raw/xfreight-playbook-rfp-response.md` — seed 2026-06-14.

---

## Recent Runs

*(append-only log — never overwrite or reorder)*

- **2026-01 — AGCO RFP NOT AWARDED.** Bid against incumbent, lost on price (per the AGCO outcome doc). Lesson: next cycle, ask for the awarded rate range before pricing. Full detail in [[AGCO RFP]] and [[Decision Journal]].
