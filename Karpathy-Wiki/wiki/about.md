---
title: About this wiki
type: concept
tags: [meta, architecture]
sources: []
related: ["[[Index]]"]
---

# About this wiki

The XFreight operational knowledge base. Pipeline output and manually-dropped
notes land in `/raw`; a daily librarian pass compiles them into cross-linked
markdown pages here in `/wiki`. The goal is a queryable record of what
happened, what the numbers mean, and where decisions came from — built on top
of the same data the daily executive brief reads.

## How it's fed

Two streams flow into `/raw`:

1. **Automatic — pipeline archive.** Each scheduled workflow run drops a
   timestamped markdown file into its own subdirectory:

   - `/raw/scorecard/` — full HTML of every executive brief.
   - `/raw/goals/` — every X-Trux rate-per-mile goal calculator run.
   - `/raw/alvys/`, `/raw/samsara/`, `/raw/qb/`, `/raw/sheets/` — per-pull
     summary metadata (load counts, refresh timestamps, sheet sizes).
   - `/raw/samsara-alerts/` — fleet alert bodies (DTC faults, DVIR defects),
     plus an "all clear" marker on quiet days.

2. **Manual.** Anything you drop into `/raw/` by hand — SOPs, contract terms,
   policy notes, post-mortems, driver records — becomes input for the next
   compile. The librarian treats these the same as automatic feeds.

## How it's compiled

`.github/workflows/karpathy_compile.yml` runs daily at 6:15am CST (after the
executive brief lands in `/raw/scorecard/`). It calls Claude with the
librarian rules in `/CLAUDE.md`, sends the trailing 30 days of `/raw` plus
the current state of `/wiki`, and writes back updated pages.

Hard guardrails:
- The librarian never modifies `/raw`. It's an immutable source-of-truth log.
- All output goes under `/wiki`. The workflow rejects commits that touch
  anything else.

## What pages will appear

Once the daily compile starts producing output (waiting on
`CLAUDE_CODE_OAUTH_TOKEN` setup), expect pages organized as:

- **Customers** — one page per XFreight customer (e.g. `[[Berry Plastics]]`,
  `[[CH Robinson]]`), with revenue history, AR aging behavior, recurring
  issues, contract notes.
- **Drivers / Trucks** — one page per driver and per truck unit, drawing on
  safety events, mileage, deadhead patterns, settlement weeks.
- **KPIs** — definition pages for the brief's metrics
  (`[[Dead Head Percentage]]`, `[[Revenue Per Mile]]`, `[[Operating Ratio]]`)
  explaining the formula, scope, and what counts as good.
- **Operational events** — links from briefs that flagged a specific
  customer/truck/driver back to that entity's page.
- **Reports** — the daily briefs themselves as references; each new brief
  cross-links into the entity pages it mentions.

The librarian also tracks **contradictions across sources** — for example, if
the QB AR snapshot disagrees with the Alvys AR for a customer, the customer
page will note both and link to the briefs that surfaced the gap.

## Reading the wiki

- In Obsidian: open this folder as a vault. The graph view shows how entities
  connect. `[[Wikilinks]]` are clickable.
- In GitHub: browse from
  https://github.com/jeffxtrux-svg/alvys-pipeline/tree/main/Karpathy-Wiki/wiki —
  the markdown renders inline.
- For a chat session (Claude.ai or Claude Code on the web): paste the file
  content or share the GitHub link to the page you want context on.

## See also

- [[Index]] — the full map of compiled pages.

## Sources

This page is meta — it has no `/raw` source. The auto-compiled pages will
each cite the `/raw` files they came from in a Sources section, per the
librarian rules.
