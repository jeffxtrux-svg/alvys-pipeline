# Jeff vs JB — how each tracks the month (captured 2026-06-15)

> Not really a disagreement — two different mental models for "how is
> the month going?" that coexist. Each has a preferred tool. Important
> framing for any future brief / report work, because it tells you who
> the audience is for a *fact-based* surface vs a *forecast-based* one.

## Jeff — facts-first (lagging)

- Uses only what's **already delivered, billed, and invoiced**.
- Reasoning: 100% accurate, no estimation error to argue about.
- Preferred tools: **Power BI** + the **daily executive brief** (both
  are fact-based / lagging by design).
- Mental model: "I won't count a load until it's a number in QuickBooks."

## JB — forecast-first (leading)

- Wants a **solid estimate** for how the month will land, including
  **open loads** in the projection.
- Reasoning: planning beats reaction — if the trajectory is short, he
  wants to know mid-month, not month-end.
- Preferred tool: the **MTD upload** that lands in the morning email
  (`daily_upload.yml`).
- Current trust state: **still validating** — JB compares the MTD
  upload against his own numbers until he trusts it. Treat the MTD
  upload as "in JB's validation period" when designing changes.
- Mental model: "I want to see where we'll land, even if the number
  flexes."

## Why this matters for future brief work

- **Don't try to consolidate** these into a single view. Two brains,
  two tools — that's the design, not an accident.
- **Forecast surfaces are JB-shaped.** Anything that projects (e.g.,
  the OTD early-warning page from the 2026-06-15 wishlist, or any
  "month will land at $X" tile) is fundamentally a JB / forecast
  surface. Jeff will look at it, but his trust is in the facts page.
- **Facts surfaces are Jeff-shaped.** Anything strictly delivered /
  billed / invoiced is a Jeff surface. The executive brief and Power
  BI are the canonical ones.
- **The MTD upload is JB-primary until validated.** When the brief or
  upload changes shape, ship the change *and* hold off pushing the
  number to anyone outside JB until he's compared the new version to
  his own working numbers.
- **Disagreements about "what the month is" usually trace to this
  split** — facts vs forecast. Surface the framing explicitly when
  Jeff and JB compare numbers.

## What this doesn't capture

- **Dan's tracking style** — not asked tonight; ask on a future drive
  home (likely operational / load-coverage cadence rather than
  financial month-end).
- **Where they actually disagree on decisions** (not tracking style).
  This page is the tracking-philosophy split only.
