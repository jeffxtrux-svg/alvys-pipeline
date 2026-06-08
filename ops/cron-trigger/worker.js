// Cloudflare Worker — off-GitHub backstop trigger for the XFreight morning
// emails (executive scorecard brief + daily MTD upload).
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
// What it triggers (and why it never double-sends)
// ------------------------------------------------
// It dispatches the two *healthcheck* workflows, NOT the primary jobs:
//   * scorecard_healthcheck.yml
//   * daily_upload_healthcheck.yml
// Each healthcheck checks the OneDrive "sent-{today}.txt" marker and only
// re-fires the real scorecard / daily-upload job when today's email hasn't
// gone out yet. So triggering this every morning is idempotent:
//   - Normal morning (GitHub cron worked, marker present)  → healthcheck no-ops.
//   - Drop morning   (no marker)                           → healthcheck recovers.
// workflow_dispatch also bypasses the healthchecks' CT-hour gate, so they run
// immediately regardless of the season/hour the Worker fires.
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
const WORKFLOWS = [
  "scorecard_healthcheck.yml",
  "daily_upload_healthcheck.yml",
];

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

async function dispatchAll(token) {
  const results = await Promise.allSettled(
    WORKFLOWS.map((wf) => dispatch(wf, token)),
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
  // Fired by the cron triggers in wrangler.toml.
  async scheduled(event, env, ctx) {
    if (!env.GH_TOKEN) throw new Error("GH_TOKEN secret is not set");
    await dispatchAll(env.GH_TOKEN);
  },

  // Manual escape hatch: visit the Worker's URL (or curl it) to fire the
  // healthchecks on demand without waiting for the next cron slot.
  async fetch(request, env, ctx) {
    if (!env.GH_TOKEN) {
      return new Response("GH_TOKEN secret is not set\n", { status: 500 });
    }
    try {
      await dispatchAll(env.GH_TOKEN);
      return new Response(`Dispatched: ${WORKFLOWS.join(", ")}\n`);
    } catch (e) {
      return new Response(`Error: ${e.message}\n`, { status: 502 });
    }
  },
};
