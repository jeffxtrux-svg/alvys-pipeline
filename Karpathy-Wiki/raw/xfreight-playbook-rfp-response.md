# Playbook — RFP response (seed 2026-06-14)

> Source-of-record for the compiled `wiki/playbook-rfp-response.md`.
> Captures XFreight's process for responding to customer RFPs (rate-bid
> packets). Built on the AGCO 2026 RFP experience (not awarded — see
> `xfreight-agco-outcome.md`) so the next cycle can do better.
> Edit by appending.

**When to run.** Triggered by:
- An existing customer sends an annual RFP packet (typically Q4 or early Q1 for the calendar year ahead).
- A prospect invites XFreight into a bid (cold or warm).
- An existing dedicated lane is up for re-bid mid-year.

**Goal.** Submit a competitive, profitable bid that XFreight can actually execute, OR cleanly decline so we don't burn the relationship for next year.

**Pre-checks.**
1. Read the RFP packet end-to-end. Note: lanes, volumes, accessorial terms, payment terms, service requirements, technology requirements (EDI, tracking visibility), and the bid-back deadline.
2. Check our current AR aging with this customer — if there's outstanding AR, that's a flag.
3. Confirm whether we have the equipment / driver capacity to take the requested volume.
4. Pull the historical rates we've run with this customer (Alvys load history) to anchor pricing.

**Steps.**
1. **Day 1 (RFP received)** — Jeff logs it in the active opportunities list, sets a calendar reminder for the deadline minus 5 days. Initial read for "can we do this at all?" — pass to step 2 if yes, branch to decline if no.
2. **Lane-by-lane costing** — for each lane: estimated total miles (loaded + empty), driver pay/mi (current OO rate), fuel cost at current diesel, accessorials. Add target margin (X-Trux 25% / X-Linx 17.5% / one-off rates negotiable).
3. **Volume realism check** — Dan reviews: can we cover the requested loads/wk with current capacity? If not, do we add equipment for this account or bid lower volume?
4. **Pricing strategy** — Jeff + JB: do we bid to win or bid to hold the seat? AGCO 2026 lesson: do not bid significantly below cost to win a multi-lane RFP — they award based on price and the unprofitable lanes will hurt for a year.
5. **Submit by deadline minus 2 days** — never submit on the last day; gives time for clarification questions.
6. **Track award outcome** — even on losses, ask for the awarded rate by lane (some shippers share). Log in the customer file.

**Decision points.**
- **If our cost-out shows negative margin at the implied market rate** — do not bid that lane. Bid the lanes that work, decline the rest with a one-line note.
- **If the customer is currently 60+ days past due** — Jeff + JB before bidding; AR risk may outweigh new revenue.
- **If the RFP requires EDI/tracking integrations we don't have** — scope the cost of building/buying, include in the bid OR decline with reason.
- **If the customer is a strategic relationship (large existing or prospect for related work)** — JB may approve a thinner margin to hold the seat.

**Escalation.**
- JB on any bid total >$500K/year of revenue OR any sub-target margin bid.
- Outside finance review for any bid that would require capacity expansion (>5 truck additions).

**Capture.**
- Append outcome to this playbook's run log (customer, RFP year, lanes bid, lanes won, $/yr, margin %).
- If we lost, capture the awarded rate (if known) vs our bid as a decision-journal entry — were we too high, too low, or right but lost on other criteria?
- If we won, set a 90-day post-award review reminder: are the lanes performing to bid assumptions?
- If a recurring pattern emerges (e.g., losing every multi-lane RFP), add to risk register and revisit pricing strategy.

**Recent runs.**
- **2026-01 — AGCO RFP NOT AWARDED.** Bid against incumbent, lost on price (per the AGCO outcome doc). Lesson captured in `xfreight-agco-outcome.md` and the decision journal: next cycle, ask for the awarded rate range before pricing.
