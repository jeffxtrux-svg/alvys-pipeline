# Slack / Teams morning digest — Phase 3A delivery surface (seed 2026-06-14)

> Source: `src/slack_digest.py` + `.github/workflows/slack_digest.yml`
> after the June 14 Phase 3A ship. First piece of the "delivery
> surface" phase — bringing the brief to where the team already works
> (Slack/Teams) rather than only the inbox.

## What it is

A compact morning post to a Slack channel or Teams channel that
summarizes the brief at-a-glance:

- MTD revenue, margin, loads, miles, RPM (actual + goal).
- Risk Watch — count of tripped vs OK, plus the top 5 tripped signals
  with severity emoji and current-vs-threshold context.
- Decisions Graded — confirmed / mixed / wrong / pending counts plus
  the most recent non-pending decision.
- Footer link back to the full brief (when the brief URL is provided).

Designed for the morning standup view: skim in 10 seconds, click
through for detail.

## How it runs

Two triggers:

1. **Auto** — `workflow_run` on completion of the **Daily KPI
   Scorecard Email** workflow. Fires immediately after the scorecard
   commits its snapshot files to main, so the digest reads
   fresh-as-of-this-morning state.
2. **Manual** — `workflow_dispatch` from the Actions tab. Optional
   `dry_run` checkbox prints the composed payload to the log without
   POSTing — useful for previewing changes.

## Data sources (no recompute)

The digest is pure presentation. It reads three files written by the
scorecard pipeline:

| File | Written by | Contains |
|---|---|---|
| `Karpathy-Wiki/raw/snapshots/YYYY-MM-DD.json` | `scorecard_snapshots.write_snapshot` | MTD KPIs (revenue, margin, loads, AR buckets, fleet MPG, RPM) |
| `Karpathy-Wiki/wiki/risk-watch-latest.json` | `risk_watch.write_signals_snapshot` | Current state of each tracked signal (tripped/ok, current value, threshold) |
| `Karpathy-Wiki/wiki/decision-grades.json` | `decision_grader.write_grades_snapshot` | Current grade per tracked decision (confirmed / mixed / wrong / pending) |

If any source file is missing, the digest gracefully omits that
section — you'll get a smaller post rather than an error.

## Setup — what's required to enable delivery

1. **Create an incoming webhook URL** in either Slack or Teams.
   - **Slack:** https://api.slack.com/messaging/webhooks — create an
     app, enable incoming webhooks, install to the workspace, and
     copy the webhook URL for the target channel.
   - **Teams:** https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook
     — in the target channel: Connectors → Incoming Webhook →
     configure → copy the URL.
2. **Add it as a GitHub secret** named `SLACK_WEBHOOK_URL` on the
   `alvys-pipeline` repo. (Despite the name, the same secret holds
   either a Slack or a Teams webhook URL — both accept the same
   Block Kit payload shape.)

Without the secret, the workflow runs and exits cleanly with a log
warning ("composed but not posted") — useful for verifying the
payload before flipping delivery on.

## Local dry-run

To preview the digest content without posting anywhere:

```
python -m src.slack_digest --dry-run
```

This reads the most recent snapshot files in
`Karpathy-Wiki/raw/snapshots/` and `Karpathy-Wiki/wiki/`, composes
the Block Kit payload, and prints it as JSON.

## What it intentionally doesn't do (yet)

- **Doesn't track read state** — every morning it posts a fresh
  digest; there's no "you have N unread risk changes since
  yesterday." Phase 3 add-on if it proves useful.
- **Doesn't accept replies / Q&A** — that's the Slack-bot piece in
  the broader Phase 3 plan, separate workflow + bot identity.
- **Doesn't customize per recipient** — single channel target. If
  the team wants different views for Logistics vs Safety vs
  Finance, route to different channels via separate webhooks.

## Related

- `xfreight-daily-scorecard-email.md` — the full brief this digest
  summarizes.
- Phase 2B `Karpathy-Wiki/wiki/risk-signals.yml` — the signals the
  Risk Watch section displays.
- Phase 2C `Karpathy-Wiki/wiki/decision-outcomes.yml` — the
  predictions the Decisions Graded section displays.
