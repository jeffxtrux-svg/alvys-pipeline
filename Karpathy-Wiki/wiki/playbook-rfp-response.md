---
title: Playbook — RFP Response
type: playbook
tags: [playbook, sales, rfp, customers, pricing]
status: active
owner: "Jeff Hannahs (BD — lane costing, submission); Dan Heeren (capacity review); JB Sweere (bids >$500K/yr or sub-target margin)"
last_revised: "2026-06-14"
trigger: "An existing customer sends an annual RFP packet; a prospect invites XFreight into a bid; an existing dedicated lane is up for re-bid mid-year"
related: ["[[AGCO RFP]]", "[[Customer Portfolio]]", "[[Rate-Per-Mile Goal]]", "[[Brokerage X-Linx]]", "[[Factoring]]", "[[Decision Journal]]"]
sources: ["raw/xfreight-playbook-rfp-response.md", "raw/xfreight-agco-outcome.md"]
---

# Playbook — RFP Response

**When to run.** Triggered by:

- An existing customer sends an annual RFP packet (typically Q4 or early Q1 for the calendar year ahead).
- A prospect invites XFreight into a bid (cold or warm).
- An existing dedicated lane is up for re-bid mid-year.

**Goal.** Submit a competitive, profitable bid XFreight can actually execute — or cleanly decline so the relationship is intact for next year.

**Pre-checks.**

1. Read the RFP packet end-to-end: lanes, volumes, accessorial terms, payment terms, service requirements, technology requirements (EDI, tracking visibility), bid-back deadline.
2. Check current AR aging with this customer. Outstanding AR is a red flag before bidding more revenue.
3. Confirm whether XFreight has the equipment/driver capacity to take the requested volume.
4. Pull historical rates for this customer from Alvys to anchor pricing.

---

## Steps

1. **Day 1 (RFP received)** — Jeff logs it in the active opportunities list, sets a calendar reminder at deadline minus 5 days. Initial read: "can we do this at all?" — yes → step 2, no → decline cleanly.
2. **Lane-by-lane costing** — for each lane: estimated total miles (loaded + empty), driver pay/mi (current OO rate), fuel cost at current diesel, accessorials. Add target margin: X-Trux 25% / X-Linx 17.5% / one-off negotiable. See [[Rate-Per-Mile Goal]] for the cost-out methodology.
3. **Volume realism check** — Dan reviews: can current capacity cover the requested loads/week? If not, bid lower volume or commit to adding equipment.
4. **Pricing strategy** — Jeff + JB: bid to win or bid to hold the seat? **AGCO 2026 lesson:** do not bid significantly below cost on a multi-lane RFP — AGCO awards on price and the unprofitable lanes hurt for a year. See [[AGCO RFP]].
5. **Submit by deadline minus 2 days** — never submit on the last day; leaves time for clarification questions.
6. **Track award outcome** — even on losses, ask for the awarded rate by lane (some shippers share). Log in the customer file and the run log below.

---

**Decision points.**

- **If cost-out shows negative margin at the implied market rate** — do not bid that lane. Bid the lanes that work; decline the rest with a one-line note.
- **If the customer is currently 60+ days past due** — Jeff + JB before bidding; AR risk may outweigh new revenue.
- **If the RFP requires EDI/tracking integrations XFreight doesn't have** — scope the cost of building/buying; include in the bid OR decline with reason.
- **If the customer is a strategic relationship (large existing or prospect for related work)** — JB may approve a thinner margin to hold the seat.

**Escalation.**

- JB on any bid total >$500K/year of revenue OR any sub-target margin bid.
- Outside finance review for any bid requiring capacity expansion (>5 additional trucks).

**Capture.**

- Append outcome to the run log below (customer, RFP year, lanes bid, lanes won, $/yr, margin %).
- If lost, capture the awarded rate vs our bid as a [[Decision Journal]] entry — were we too high, too low, or right but lost on other criteria?
- If won, set a 90-day post-award review reminder: are the lanes performing to bid assumptions?
- Recurring losses on multi-lane RFPs → add to [[Risk Register]] and revisit pricing strategy.

---

## Recent Runs *(append-only)*

**2026-01 — AGCO RFP NOT AWARDED.** Bid against incumbent, lost on price. AGCO's criteria: "best price per lane" / "low-cost carrier." Asset-based X-Trux rates were structurally higher than asset-light brokerage competitors; no reefer capacity for Hazmat/Temp Control Van lanes was a second gap. Next cycle expected late 2026/early 2027 — ask for the awarded rate range before pricing. Full lesson captured in [[AGCO RFP]].

## Connections

- [[AGCO RFP]] — the reference case; outcome and lessons documented.
- [[Customer Portfolio]] — tracks all active, historical, and prospective customers.
- [[Rate-Per-Mile Goal]] — the cost-out method that underpins lane pricing.
- [[Brokerage X-Linx]] — X-Linx is the brokerage arm that can bridge lanes XFreight can't cover with own-fleet.
- [[Decision Journal]] — capture every lost bid's price-vs-market comparison.

## Sources

- `raw/xfreight-playbook-rfp-response.md`
- `raw/xfreight-agco-outcome.md`
