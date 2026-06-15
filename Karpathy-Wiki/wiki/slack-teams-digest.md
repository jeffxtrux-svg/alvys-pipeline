---
title: Slack / Teams Morning Digest
type: concept
tags: [automation, slack, teams, digest, delivery-surface]
sources: ["raw/xfreight-slack-teams-digest.md"]
related: ["[[Daily Scorecard Email]]", "[[Daily Schedule]]", "[[Data Pipeline Architecture]]", "[[Risk Register]]", "[[Decision Journal]]"]
---

# Slack / Teams Morning Digest

## Summary

A compact morning post to a Slack or Teams channel that summarizes the daily executive brief at a glance — MTD KPIs, Risk Watch signals, and Decisions Graded status. Introduced in Phase 3A (shipped 2026-06-14). Runs automatically after the daily scorecard email completes.

## What It Contains

- **MTD KPIs** — revenue, margin, loads, miles, RPM (actual + goal).
- **Risk Watch** — count of tripped vs. OK signals; top 5 tripped signals with severity emoji and current-vs-threshold context. Sourced from `wiki/risk-watch-latest.json`.
- **Decisions Graded** — confirmed / mixed / wrong / pending counts; most recent non-pending decision. Sourced from `wiki/decision-grades.json`.
- **Footer** — link back to the full brief (when a brief URL is provided).

Designed for the morning standup view: skim in 10 seconds, click through for detail.

## How It Runs

**Trigger 1 — Auto:** `workflow_run` on completion of the Daily KPI Scorecard Email workflow. Fires immediately after the scorecard commits its snapshot files to `main`, so the digest reads this-morning's state.

**Trigger 2 — Manual:** `workflow_dispatch` from the Actions tab. An optional `dry_run` checkbox prints the composed payload to the log without POSTing — useful for verifying changes before enabling delivery.

## Data Sources (No Recompute)

The digest is pure presentation. It reads three files written by the scorecard pipeline:

| File | Written by | Contains |
|---|---|---|
| `Karpathy-Wiki/raw/snapshots/YYYY-MM-DD.json` | `scorecard_snapshots.write_snapshot` | MTD KPIs (revenue, margin, loads, AR buckets, fleet MPG, RPM) |
| `Karpathy-Wiki/wiki/risk-watch-latest.json` | `risk_watch.write_signals_snapshot` | Current state of each tracked signal (tripped/ok, current value, threshold) |
| `Karpathy-Wiki/wiki/decision-grades.json` | `decision_grader.write_grades_snapshot` | Current grade per tracked decision (confirmed / mixed / wrong / pending) |

If any source file is missing, the digest gracefully omits that section — a smaller post rather than an error.

## Setup — Enabling Delivery

1. Create an incoming webhook URL in Slack or Teams:
   - **Slack:** Create an app → enable Incoming Webhooks → install to workspace → copy webhook URL for the target channel.
   - **Teams:** Target channel → Connectors → Incoming Webhook → configure → copy URL.
2. Add it as a GitHub secret named `SLACK_WEBHOOK_URL` on the `alvys-pipeline` repo. (The same secret holds either a Slack or Teams URL — both accept the Block Kit payload shape.)

Without the secret, the workflow runs and exits cleanly with a log warning ("composed but not posted") — useful for payload preview before flipping delivery on.

## Local Dry-Run

```
python -m src.slack_digest --dry-run
```

Reads the most recent snapshot files from `Karpathy-Wiki/raw/snapshots/` and `Karpathy-Wiki/wiki/`, composes the Block Kit payload, and prints it as JSON without posting.

## What It Intentionally Doesn't Do Yet

- **Doesn't track read state** — every morning it posts fresh; there's no "N unread risk changes since yesterday."
- **Doesn't accept replies / Q&A** — the Slack-bot piece is a separate Phase 3 workflow + bot identity.
- **Doesn't customize per recipient** — single channel target. Different views for Logistics vs Safety vs Finance would require separate webhooks to separate channels.

## Connections

- [[Daily Scorecard Email]] — the full 13-page brief this digest summarizes.
- [[Risk Register]] and `wiki/risk-signals.yml` — the signals the Risk Watch section displays.
- [[Decision Journal]] and `wiki/decision-outcomes.yml` — the predictions the Decisions Graded section displays.
- [[Employee Responsibilities]] — Phase 3B will add per-channel routing so each brief type posts to its owner's channel.

## Sources

- `raw/xfreight-slack-teams-digest.md`
