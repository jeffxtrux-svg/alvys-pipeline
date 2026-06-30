---
title: Slack & Teams Digest
type: concept
tags: [technology, automation, slack, teams, digest, brief]
sources: ["raw/xfreight-slack-teams-digest.md"]
related: ["[[Daily Scorecard Email]]", "[[Daily Schedule]]", "[[Risk Register]]", "[[Decision Journal]]"]
---

# Slack & Teams Digest

A compact morning post to a Slack or Teams channel summarizing the daily brief at a glance. Designed for the standup view — skim in 10 seconds, click through for detail. Ships as part of Phase 3A of the delivery-surface expansion (June 2026).

## Summary

Fires automatically after the daily scorecard email completes, posting a single-screen KPI summary to whichever Slack or Teams channel is configured via the `SLACK_WEBHOOK_URL` secret. If the secret isn't set, the workflow runs but skips posting — useful for previewing output before enabling delivery.

## What the Digest Contains

- **MTD KPIs** — revenue, margin, loads, miles, RPM (actual + goal).
- **Risk Watch** — count of tripped vs. OK signals, plus the top 5 tripped signals with severity emoji and current-vs-threshold context.
- **Decisions Graded** — confirmed / mixed / wrong / pending counts, plus the most recent non-pending decision.
- **Footer** — link back to the full 13-page brief (when a brief URL is configured).

## How It Runs

Two triggers:

1. **Auto (`workflow_run`)** — fires on completion of the daily scorecard email workflow. The digest reads the same snapshot files the scorecard just wrote, so it's always current as of this morning.
2. **Manual (`workflow_dispatch`)** — optional `dry_run` checkbox prints the composed Block Kit payload to the Actions log without posting — useful for previewing changes to the digest layout.

Local preview without posting:
```
python -m src.slack_digest --dry-run
```

## Data Sources (No Recompute)

The digest is pure presentation — it reads three files written by the scorecard pipeline and doesn't recompute any metrics:

| File | Written by | Contains |
|---|---|---|
| `Karpathy-Wiki/raw/snapshots/YYYY-MM-DD.json` | `scorecard_snapshots.write_snapshot` | MTD KPIs (revenue, margin, loads, AR buckets, fleet MPG, RPM) |
| `Karpathy-Wiki/wiki/risk-watch-latest.json` | `risk_watch.write_signals_snapshot` | Current state of each tracked signal (tripped/ok, value, threshold) |
| `Karpathy-Wiki/wiki/decision-grades.json` | `decision_grader.write_grades_snapshot` | Grade per tracked decision (confirmed / mixed / wrong / pending) |

If any source file is missing, the digest gracefully omits that section rather than erroring.

## Setup — Enabling Delivery

1. **Create a webhook URL** in Slack or Teams:
   - **Slack:** create an app, enable incoming webhooks, install to workspace, copy the URL for the target channel.
   - **Teams:** in the target channel → Connectors → Incoming Webhook → configure → copy URL.
2. **Add the URL as a GitHub secret** named `SLACK_WEBHOOK_URL` on the `alvys-pipeline` repo. Both Slack and Teams webhook URLs work — the Block Kit payload shape is compatible with both.

Without the secret the workflow exits with a warning ("composed but not posted") — the payload is still available in the Actions log for review.

## What It Intentionally Doesn't Do (Yet)

- **No read-state tracking** — posts a fresh digest every morning; no "N unread risk changes since yesterday."
- **No replies / Q&A** — that's the Slack-bot piece in the broader Phase 3 plan, separate workflow + bot identity.
- **No per-recipient customization** — single channel target. For different views per team (Logistics vs. Safety vs. Finance), route to different channels via separate webhooks.

## Connections

- [[Daily Scorecard Email]] — the full 13-page brief this digest summarizes.
- [[Daily Schedule]] — digest fires immediately after the 5am scorecard email workflow completes.
- [[Risk Register]] / [[risk-signals.yml]] — the signals populating the Risk Watch section.
- [[Decision Journal]] / [[decision-outcomes.yml]] — the decisions graded in the Decisions Graded section.

## Sources

- `raw/xfreight-slack-teams-digest.md` — Phase 3A ship notes (June 14, 2026).
