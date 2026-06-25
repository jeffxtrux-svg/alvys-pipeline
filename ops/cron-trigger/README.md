# Off-GitHub backstop (Cloudflare Worker)

A tiny Cloudflare Worker that keeps two GitHub-cron-dependent automations alive
**even when GitHub Actions drops its scheduled crons**:

1. the customer-facing **morning emails** (scorecard / daily-upload / safety), and
2. the live **XFreight ETA tracker** (`xfreight_etas.yml`), refreshed every 30 min.

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

The Worker branches on which cron fired (`event.cron`).

### Morning emails (once/day, 5:30am Central)

It asks GitHub to run the **healthcheck** workflows (not the primary jobs):

- `scorecard_healthcheck.yml`
- `daily_upload_healthcheck.yml`
- `safety_compliance_healthcheck.yml`

Each healthcheck checks the OneDrive `…/sent-{today}.txt` marker and only
re-fires the real job if today's email hasn't gone out. So firing this every
morning is **idempotent — it never double-sends**:

| Morning | Marker | Result |
|---|---|---|
| Normal (GitHub cron worked) | present | healthcheck no-ops |
| Drop (GitHub cron failed)   | absent  | healthcheck dispatches the real job → email goes out |

`workflow_dispatch` also bypasses the healthchecks' CT-hour gate, so they run
immediately whatever hour/season the Worker fires.

### XFreight ETA tracker (every 30 min)

It dispatches `xfreight_etas.yml` directly at **:15 and :45**, interleaving with
GitHub's own `:00/:30` cron on the same workflow. The two schedulers are
independent (GitHub vs Cloudflare), so:

| Slot | Fired by | Effect |
|---|---|---|
| :00, :30 | GitHub cron | normal refresh |
| :15, :45 | this Worker | normal refresh |
| GitHub drops :00 | Worker still fires :15 | gap stays ≤ ~15 min |
| GitHub cron outage (all slots) | Worker still fires :15/:45 | tracker keeps refreshing every 30 min |

The ETA run is **idempotent** — it fully rewrites the OneDrive file and posts a
Teams card only when the late-load set changes (tracked in `eta_state.json`) —
so a redundant dispatch never produces duplicate alerts.

## Schedule

`wrangler.toml` arms three cron triggers:

**Morning emails — 5:30am Central, year-round.** Cloudflare cron is fixed UTC
with no DST handling, so both seasonal 5:30am slots are armed and the Worker's
own `America/Chicago` hour-gate (`centralHour()` in `worker.js`) fires only the
one that actually lands on 5:30am Central:

- `30 10 * * *` → 5:30am CDT (summer) / 4:30am CST → gated off in winter
- `30 11 * * *` → 6:30am CDT → gated off in summer / 5:30am CST (winter)

So exactly one fire passes the gate each morning, at 5:30am Central, with no
manual cron edits at the DST flip.

**ETA tracker — every 30 min, around the clock:**

- `15,45 * * * *` → dispatches `xfreight_etas.yml` at :15/:45 (no DST gate;
  interleaves with GitHub's :00/:30 cron).

(The manual `fetch` endpoint ignores the gate: hit `/` for the healthchecks or
`/eta` for the ETA tracker, on demand, any time.)

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
  It returns `Dispatched: scorecard_healthcheck.yml, daily_upload_healthcheck.yml, safety_compliance_healthcheck.yml`.
  Then watch the healthcheck runs appear under the repo's Actions tab. Hit
  `…workers.dev/eta` to dispatch the ETA tracker on demand instead.
- **Logs:** `wrangler tail` (live) or the Workers dashboard (observability is
  enabled in `wrangler.toml`).
- **Rotate the token:** re-run `wrangler secret put GH_TOKEN` with a new PAT;
  no redeploy needed.

## Cost

Free. A few cron invocations a day, each making two small GitHub API calls —
far under Cloudflare's free Workers limits, and the triggered healthchecks are
~30-second GitHub Actions runs.
