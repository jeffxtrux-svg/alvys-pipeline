"""Send a pass/fail upload-status email after each 2-hour refresh cycle.

Queries the GitHub Actions API for workflow runs in the last 3 hours,
summarises pass / fail / skipped for the four refresh workflows, and sends
a compact HTML email to jeff@xfreight.net via Microsoft Graph.

Run from the upload_status.yml workflow after each 2-hour slot.
Env vars: AZURE_*, ONEDRIVE_USER_UPN, GH_TOKEN, GITHUB_REPOSITORY.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

from src.onedrive_upload import get_token

log = logging.getLogger("upload_status")
logging.basicConfig(level=logging.INFO, format="%(message)s")

GRAPH = "https://graph.microsoft.com/v1.0"
GH_API = "https://api.github.com"

REFRESH_WORKFLOWS = {
    "refresh.yml":            "Alvys",
    "samsara_refresh.yml":    "Samsara",
    "qb_refresh.yml":         "QuickBooks",
    "sambasafety_refresh.yml":"SambaSafety",
}

GOOD = "#1a7f37"
BAD  = "#cf222e"
WARN = "#9a6700"
MUTE = "#57606a"
BG   = "#f6f8fa"


def _gh_headers() -> dict:
    token = os.environ.get("GH_TOKEN", "")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _recent_runs(repo: str, workflow_file: str, since: datetime) -> list[dict]:
    """Return workflow runs created after `since` (UTC), newest first."""
    url = f"{GH_API}/repos/{repo}/actions/workflows/{workflow_file}/runs"
    params = {"per_page": 10, "created": f">={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"}
    try:
        r = requests.get(url, headers=_gh_headers(), params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("workflow_runs", [])
    except Exception as exc:
        log.warning("GitHub API error for %s: %s", workflow_file, exc)
        return []


def _status_icon(conclusion: str | None, status: str | None) -> tuple[str, str]:
    """Return (emoji, colour) for a run."""
    if status in ("in_progress", "queued", "waiting"):
        return "⏳", WARN
    c = (conclusion or "").lower()
    if c == "success":
        return "✅", GOOD
    if c in ("failure", "timed_out", "startup_failure"):
        return "❌", BAD
    if c in ("skipped", "cancelled"):
        return "⏭", MUTE
    return "❓", MUTE


def _row(label: str, icon: str, colour: str, detail: str) -> str:
    return (
        f"<tr>"
        f"<td style='padding:6px 12px;font-weight:600;color:#24292f'>{label}</td>"
        f"<td style='padding:6px 12px;font-size:18px'>{icon}</td>"
        f"<td style='padding:6px 12px;color:{colour};font-weight:700'>{detail}</td>"
        f"</tr>"
    )


def send_status_email(token: str, from_upn: str, to: str, rows: list[tuple]) -> None:
    now_ct = datetime.now(timezone(timedelta(hours=-5)))  # CDT approx; display only
    ct_str = now_ct.strftime("%b %-d · %-I:%M %p CT")
    subject = f"Upload status · {ct_str}"

    any_failure = any(icon == "❌" for _, icon, _, _ in rows)
    header_colour = BAD if any_failure else GOOD
    header_text = "⚠️ Upload failure detected" if any_failure else "✅ All uploads successful"

    table_rows = "".join(_row(label, icon, colour, detail) for label, icon, colour, detail in rows)

    html = f"""
<div style='font-family:Arial,sans-serif;max-width:560px;margin:0 auto'>
  <div style='background:{header_colour};color:#fff;padding:10px 16px;border-radius:6px 6px 0 0;font-weight:700'>
    {header_text}
  </div>
  <div style='border:1px solid #d0d7de;border-top:none;border-radius:0 0 6px 6px;background:#fff'>
    <table style='width:100%;border-collapse:collapse'>
      <thead>
        <tr style='background:{BG};border-bottom:1px solid #d0d7de'>
          <th style='padding:6px 12px;text-align:left;color:{MUTE};font-size:11px;text-transform:uppercase'>Workflow</th>
          <th style='padding:6px 12px;text-align:left;color:{MUTE};font-size:11px;text-transform:uppercase'></th>
          <th style='padding:6px 12px;text-align:left;color:{MUTE};font-size:11px;text-transform:uppercase'>Result</th>
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
    <p style='margin:8px 12px;font-size:11px;color:{MUTE}'>
      Checked at {ct_str} &middot; last 3 hours of runs
    </p>
  </div>
</div>
"""

    url = f"{GRAPH}/users/{from_upn}/sendMail"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }},
        timeout=30,
    )
    if resp.status_code == 202:
        log.info("Status email sent to %s", to)
    else:
        log.error("Email send failed: %s %s", resp.status_code, resp.text[:200])
        sys.exit(1)


def main() -> int:
    token = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )
    from_upn = os.environ.get("ONEDRIVE_USER_UPN", "jeff@xfreight.net")
    to_email = os.environ.get("STATUS_EMAIL_TO", "jeff@xfreight.net")
    repo = os.environ.get("GITHUB_REPOSITORY", "jeffxtrux-svg/alvys-pipeline")

    since = datetime.now(timezone.utc) - timedelta(hours=3)
    rows: list[tuple] = []

    for wf_file, label in REFRESH_WORKFLOWS.items():
        runs = _recent_runs(repo, wf_file, since)
        if not runs:
            rows.append((label, "❓", MUTE, "No run found in last 3 hours"))
            continue
        # Most recent run
        run = runs[0]
        icon, colour = _status_icon(run.get("conclusion"), run.get("status"))
        conclusion = (run.get("conclusion") or run.get("status") or "unknown").replace("_", " ")
        started = run.get("created_at", "")[:16].replace("T", " ") + " UTC"
        rows.append((label, icon, colour, f"{conclusion} · {started}"))
        log.info("%s: %s %s", label, icon, conclusion)

    send_status_email(token, from_upn, to_email, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
