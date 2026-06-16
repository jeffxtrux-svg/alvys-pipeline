---
title: Jeff JB Tracking Philosophy
type: concept
tags: [leadership, reporting, kpi, philosophy, finance]
sources: ["raw/xfreight-jeff-vs-jb-tracking-philosophy.md", "raw/xfreight-dan-tracking-and-driver-connection.md"]
related: ["[[Brief Roadmap]]", "[[Daily Scorecard Email]]", "[[Dan Tracking Driver Connection]]", "[[Employee Responsibilities]]", "[[Key People]]"]
---

# Jeff / JB Tracking Philosophy

Jeff Hannahs and JB Sweere track the month using two different mental models — facts-first (Jeff) vs. forecast-first (JB). These are not in conflict; they coexist deliberately, and each owner has a preferred tool. Understanding the split is essential for any brief or report design work.

## Summary

Jeff counts only what is already delivered, billed, and invoiced. JB wants a solid estimate for how the month will land, including open loads. Each has a primary tool: Jeff uses Power BI + the executive brief; JB uses the MTD upload. Dan's tracking style (see [[Dan Tracking Driver Connection]]) is closest to Jeff's facts-first model but with a strong skeptical streak.

## Jeff — Facts-First (Lagging)

- Uses only **already delivered, billed, and invoiced** data.
- Reasoning: 100% accurate, no estimation error to argue about.
- Preferred tools: **Power BI** + the **daily executive brief** (both are fact-based by design).
- Mental model: "I won't count a load until it's a number in QuickBooks."

## JB — Forecast-First (Leading)

- Wants a **solid estimate** for how the month will land, including **open loads** in the projection.
- Reasoning: planning beats reaction — if the trajectory is short, he wants to know mid-month, not month-end.
- Preferred tool: the **MTD upload** (`daily_upload.yml`).
- **Current trust state:** still in JB's validation period — JB compares the MTD upload against his own numbers. Treat the MTD upload as unconfirmed until he stops cross-checking.
- Mental model: "I want to see where we'll land, even if the number flexes."

## Implications for Brief Design

- **Don't consolidate.** Two brains, two tools — that is the design, not an accident.
- **Forecast surfaces are JB-shaped.** Anything that projects forward (e.g., the [[OTD Early Warning Wishlist]], or any "month will land at $X" tile) is a JB / forecast surface. Jeff will look at it but his trust stays in the facts page.
- **Facts surfaces are Jeff-shaped.** The executive brief and Power BI are canonical. Anything strictly delivered / billed / invoiced is a Jeff surface.
- **The MTD upload is JB-primary until validated.** When the brief or upload changes shape, ship the change and hold off pushing the number outside JB until he has compared the new version to his own working numbers.
- **"What the month is" disagreements** usually trace to this split — surface the framing explicitly when Jeff and JB compare numbers.

## The OTD Exception

The OTD early-warning page is forecast (projected ETAs vs. appointment times) — which would normally make it JB-shaped. Jeff explicitly overrode this (2026-06-15): OTD is binary will/won't-deliver (operational), not a financial estimate, so it does not conflict with his facts-first philosophy. He wants the OTD page on the executive brief. See [[OTD Early Warning Wishlist]].

## Connections

- [[Brief Roadmap]] — how this split drives the multiple-brief design.
- [[Dan Tracking Driver Connection]] — completes the three-person tracking picture (Dan ≈ Jeff but more skeptical).
- [[Employee Responsibilities]] — canonical brief-to-owner routing.
- [[Daily Scorecard Email]] — the primary Jeff surface.

## Sources

- `raw/xfreight-jeff-vs-jb-tracking-philosophy.md` — captured 2026-06-15.
- `raw/xfreight-dan-tracking-and-driver-connection.md` — Dan section captured same date.
