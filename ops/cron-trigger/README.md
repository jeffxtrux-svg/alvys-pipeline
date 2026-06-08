# Off-GitHub morning-email backstop (Cloudflare Worker)

A tiny Cloudflare Worker that guarantees the two customer-facing morning emails
go out **even when GitHub Actions drops its scheduled crons**.

## The problem it solves

GitHub Actions' `schedule:` cron is best-effort and silently drops runs under
platform load. On **2026-06-08** GitHub dropped this repo's entire morning
batch — every 5am scorecard slot, both daily-upload slots, *and* the 6am
healthchecks whose whole job is to recover dropped runs. Because every layer of
the existing defense-in-depth (staggered backup crons + healthchecks) is itself
built on GitHub cron, a GitHub-side outage takes them all out at once.

This Worker runs on **Cloudflare's** scheduler — outside GitHub — so it survives
a GitHub cron outage. It's the only layer that does.

## How it works

On its schedule the Worker asks GitHub to run the two **healthcheck** workflows
(not the primary jobs):

- `scorecard_healthcheck.yml`
- `daily_upload_healthcheck.yml`

Each healthcheck checks the OneDrive `…/sent-{today}.txt` marker and only
re-fires the real scorecard / daily-upload job if today's email hasn't gone out.
So firing this every morning is **idempotent — it never double-sends**:

| Morning | Marker | Result |
|---|---|---|
| Normal (GitHub cron worked) | present | healthcheck no-ops |
| Drop (GitHub cron failed)   | absent  | healthcheck dispatches the real job → email goes out |

`workflow_dispatch` also bypasses the healthchecks' CT-hour gate, so they run
immediately whatever hour/season the Worker fires.

## Schedule

Target: **5:30am Central, year-round.** Cloudflare cron is fixed UTC with no DST
handling, so `wrangler.toml` arms both seasonal 5:30am slots and the Worker's
own `America/Chicago` hour-gate (`centralHour()` in `worker.js`) fires only the
one that actually lands on 5:30am Central:

- `30 10 * * *` → 5:30am CDT (summer) / 4:30am CST → gated off in winter
- `30 11 * * *` → 6:30am CDT → gated off in summer / 5:30am CST (winter)

So exactly one fire passes the gate each morning, at 5:30am Central, with no
manual cron edits at the DST flip. (The manual `fetch` test endpoint ignores the
gate, so you can trigger it on demand any time.)

## One-time setup

Prereqs: a free [Cloudflare account](https://dash.cloudflare.com/sign-up) and
the Wrangler CLI (`npm i -g wrangler`, or use `npx wrangler …`).

1. **Mint a fine-grained GitHub PAT** at
   https://github.com/settings/personal-access-tokens/new
   - **Resource owner:** `jeffxtrux-svg`
   - **Repository access:** *Only select repositories* → `alvys-pipeline`
   - **Permissions:** Repository → **Actions: Read and write** (nothing else)
   - **Expiration:** pick a date and set a calendar reminder to rotate.

2. **Authenticate Wrangler** (opens a browser once):
   ```bash
   wrangler login
   ```

3. **Store the PAT as a Worker secret** (encrypted, never in git):
   ```bash
   cd ops/cron-trigger
   wrangler secret put GH_TOKEN     # paste the PAT when prompted
   ```

4. **Deploy:**
   ```bash
   wrangler deploy
   ```

That's it. The cron triggers activate on deploy.

## Verify / operate

- **Fire it now** without waiting for cron — open the Worker's `*.workers.dev`
  URL in a browser, or:
  ```bash
  curl https://alvys-scorecard-cron.<your-subdomain>.workers.dev
  ```
  It returns `Dispatched: scorecard_healthcheck.yml, daily_upload_healthcheck.yml`.
  Then watch the two healthcheck runs appear under the repo's Actions tab.
- **Logs:** `wrangler tail` (live) or the Workers dashboard (observability is
  enabled in `wrangler.toml`).
- **Rotate the token:** re-run `wrangler secret put GH_TOKEN` with a new PAT;
  no redeploy needed.

## Cost

Free. A few cron invocations a day, each making two small GitHub API calls —
far under Cloudflare's free Workers limits, and the triggered healthchecks are
~30-second GitHub Actions runs.
