// Cloudflare Worker — off-GitHub backstop trigger for XFreight automations.
//
// Why this exists
// ---------------
// GitHub Actions' scheduled cron is best-effort and silently DROPS runs under
// platform load. On 2026-06-08 it dropped this repo's entire morning batch —
// every 5am scorecard slot, both daily-upload slots, AND the 6am healthchecks
// that exist to recover dropped runs. The whole defense-in-depth design is
// built on GitHub cron, so a GitHub-side outage takes out every layer at once.
//
// This Worker runs on Cloudflare's scheduler — completely outside GitHub — so a
// GitHub cron outage can't take it down too. It's the one layer that survives.
//
// What it triggers
// ----------------
// 1. Morning emails (once/day, 5:30am Central) — dispatches the *healthcheck*
//    workflows, NOT the primary jobs:
//      * scorecard_healthcheck.yml
//      * daily_upload_healthcheck.yml
//      * safety_compliance_healthcheck.yml
//    Each healthcheck checks the OneDrive "sent-{today}.txt" marker and only
//    re-fires the real job when today's email hasn't gone out yet. So firing
//    them every morning is idempotent:
//      - Normal morning (GitHub cron worked, marker present)  → healthcheck no-ops.
//      - Drop morning   (no marker)                           → healthcheck recovers.
//    workflow_dispatch bypasses the healthchecks' CT-hour gate, so they run
//    immediately regardless of the season/hour the Worker fires.
//
// 2. XFreight ETA tracker (every 30 min, at :15/:45) — dispatches the live
//    tracker workflow (xfreight_etas.yml) directly. GitHub's own cron fires it
//    at :00/:30; this Worker fires it at :15/:45, so the two INDEPENDENT
//    schedulers interleave to a 15-min effective cadence. If GitHub drops a
//    slot (or has a total cron outage), Cloudflare still refreshes the tracker
//    30 min later, and vice-versa. The ETA run is idempotent — it fully
//    rewrites the OneDrive file and only posts a Teams card when the late-load
//    set actually changes (state tracked in eta_state.json) — so a redundant
//    dispatch never produces duplicate alerts.
//
// Setup (one time) — see README.md in this folder for the full walkthrough:
//   1. Mint a fine-grained GitHub PAT scoped to jeffxtrux-svg/alvys-pipeline
//      ONLY, with Repository permission "Actions: Read and write".
//   2. wrangler secret put GH_TOKEN      (paste the PAT — stored encrypted)
//   3. wrangler deploy
// The token never appears in this file or in git; it lives as a Cloudflare
// secret you control.

const OWNER = "jeffxtrux-svg";
const REPO = "alvys-pipeline";
const REF = "main";

// Marker-gated healthchecks — they self-dedupe, so firing them daily is safe.
const HEALTHCHECK_WORKFLOWS = [
  "scorecard_healthcheck.yml",
  "daily_upload_healthcheck.yml",
  "safety_compliance_healthcheck.yml",
];

// The live ETA tracker. Idempotent (rewrites OneDrive, Teams posts only on
// state change), so a redundant dispatch is always safe.
const ETA_WORKFLOW = "xfreight_etas.yml";

// The cron expression (in wrangler.toml) reserved for the ETA tracker. Fires at
// :15 and :45 to interleave with GitHub's :00/:30 cron on xfreight_etas.yml.
const ETA_CRON = "15,45 * * * *";

async function dispatch(workflow, token) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${workflow}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      // GitHub's API rejects requests without a User-Agent.
      "User-Agent": "alvys-scorecard-cron-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: REF }),
  });
  // A successful workflow dispatch returns 204 No Content.
  if (res.status !== 204) {
    const body = await res.text();
    throw new Error(`${workflow} -> HTTP ${res.status}: ${body}`);
  }
  console.log(`Dispatched ${workflow} (204)`);
}

// Current hour-of-day in America/Chicago (auto-handles CST vs CDT). Used to
// gate the two morning UTC cron slots down to the single one that lands at
// 5:30am Central in the current season.
function centralHour() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    hour: "numeric",
    hourCycle: "h23",
  }).formatToParts(new Date());
  return parseInt(parts.find((p) => p.type === "hour").value, 10);
}

async function dispatchAll(workflows, token) {
  const results = await Promise.allSettled(
    workflows.map((wf) => dispatch(wf, token)),
  );
  const failures = results
    .filter((r) => r.status === "rejected")
    .map((r) => r.reason.message);
  if (failures.length) {
    // Surface failures so the invocation is marked failed in Cloudflare's
    // observability dashboard / `wrangler tail`.
    throw new Error(failures.join("; "));
  }
}

export default {
  // Fired by the cron triggers in wrangler.toml. Cloudflare passes the matching
  // cron string as event.cron, so we branch on it:
  //   * ETA_CRON ("15,45 * * * *") → dispatch the ETA tracker, all day.
  //   * the two morning slots      → dispatch the healthchecks, gated to 5am CT.
  async scheduled(event, env, ctx) {
    if (!env.GH_TOKEN) throw new Error("GH_TOKEN secret is not set");

    // ETA tracker: every 30 min at :15/:45, interleaving with GitHub's :00/:30
    // cron so a dropped slot on either scheduler is covered by the other.
    if (event.cron === ETA_CRON) {
      await dispatch(ETA_WORKFLOW, env.GH_TOKEN);
      return;
    }

    // Morning email backstop: only the 5am-Central slot passes the gate.
    const h = centralHour();
    if (h !== 5) {
      console.log(`Central hour is ${h}, not the 5am slot — skipping.`);
      return;
    }
    await dispatchAll(HEALTHCHECK_WORKFLOWS, env.GH_TOKEN);
  },

  // Manual escape hatch: hit the Worker's URL to fire on demand without waiting
  // for cron. Path "/eta" dispatches the ETA tracker; anything else dispatches
  // the morning healthchecks.
  async fetch(request, env, ctx) {
    if (!env.GH_TOKEN) {
      return new Response("GH_TOKEN secret is not set\n", { status: 500 });
    }
    const path = new URL(request.url).pathname;
    try {
      if (path === "/eta") {
        await dispatch(ETA_WORKFLOW, env.GH_TOKEN);
        return new Response(`Dispatched: ${ETA_WORKFLOW}\n`);
      }
      await dispatchAll(HEALTHCHECK_WORKFLOWS, env.GH_TOKEN);
      return new Response(`Dispatched: ${HEALTHCHECK_WORKFLOWS.join(", ")}\n`);
    } catch (e) {
      return new Response(`Error: ${e.message}\n`, { status: 502 });
    }
  },
};
