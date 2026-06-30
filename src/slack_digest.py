"""Slack digest — Phase 3A delivery surface.

Composes a compact morning digest of the brief's key state and posts
it to a Slack/Teams incoming-webhook URL. Designed to run as a
separate workflow immediately after the scorecard email so the digest
reads the snapshot files the brief just wrote — no recompute.

Sources (all mirrored to OneDrive by the scorecard run that precedes this,
under the "Scorecard" folder — NOT read from git: Karpathy-Wiki/raw is
gitignored and the scorecard workflow's commit step never stages
Karpathy-Wiki/wiki either, so neither ever reaches a checkout of main):
  * Scorecard/snapshot-latest.json — today's KPIs (collect_kpis output:
    mtd_revenue, qb_ar_91_plus, fleet_mpg, ...).
  * Scorecard/risk-watch-latest.json — current risk signals with
    tripped/ok state.
  * Scorecard/decision-grades.json — current decision grades.
Falls back to the local Karpathy-Wiki/raw|wiki files when OneDrive creds
aren't set, for local dry-runs against files written in the same session.

Output: a Slack Block Kit payload posted to SLACK_WEBHOOK_URL (env var).
The webhook URL is the only secret needed; both Slack and Teams
support incoming-webhook URLs with the same Block Kit / message
shape.

Design intent: this module owns ONLY presentation + delivery. Data
production stays in the scorecard pipeline. If the digest is wrong,
the fix is in the source files / risk-signals YAML / decision
outcomes YAML — not here.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

import requests

log = logging.getLogger("slack_digest")

_REPO = Path(__file__).resolve().parent.parent
_SNAP_DIR = _REPO / "Karpathy-Wiki" / "raw" / "snapshots"
_WIKI_DIR = _REPO / "Karpathy-Wiki" / "wiki"
_ONEDRIVE_FOLDER = "Scorecard"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        log.warning("failed to read %s: %s", path, exc)
        return None


def _onedrive_json(filename: str) -> dict | None:
    """Best-effort read of a Scorecard/<filename> mirror from OneDrive.

    This is the live source: the scorecard run that precedes this digest
    writes its snapshot/signals/grades to a fresh GitHub Actions checkout,
    which is gitignored and discarded when that job ends — local files are
    only ever present for local dry-runs, not in CI. Returns None if Azure
    creds aren't set or the file isn't there yet."""
    try:
        from src.onedrive_upload import download_file, get_token_from_env
        token, upn = get_token_from_env()
        if not token:
            return None
        raw = download_file(token, upn, f"{_ONEDRIVE_FOLDER}/{filename}")
        return json.loads(raw)
    except Exception as exc:
        log.info("OneDrive read of %s unavailable: %s", filename, exc)
        return None


def _latest_snapshot(today: date | None = None) -> dict | None:
    """Return the latest KPI snapshot — OneDrive mirror first (the live
    source in CI), falling back to local files for local dry-runs."""
    onedrive = _onedrive_json("snapshot-latest.json")
    if onedrive is not None:
        return onedrive
    today = today or date.today()
    todays = _SNAP_DIR / f"{today.isoformat()}.json"
    if todays.exists():
        return _read_json(todays)
    if not _SNAP_DIR.exists():
        return None
    candidates = sorted(_SNAP_DIR.glob("*.json"))
    if not candidates:
        return None
    return _read_json(candidates[-1])


def _money(v) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _pct(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _num(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_value(v, fmt: str) -> str:
    return {"money": _money, "pct": _pct, "int": _num, "days": lambda x: f"{int(float(x))}d"}.get(
        fmt, _num
    )(v) if v is not None else "—"


def _tripped_text(signal: dict) -> str:
    """Render the signal's tripped_text template against its value(s)."""
    tpl = signal.get("tripped_text_template") or signal.get("title", "")
    value_str = _fmt_value(signal.get("value"), signal.get("format", "int"))
    text = tpl.format(value=value_str) if "{value}" in tpl else tpl
    paired_tpl = signal.get("paired_tripped_text_template")
    paired_value = signal.get("paired_value")
    if paired_tpl and paired_value is not None:
        paired_str = _fmt_value(paired_value, signal.get("format", "int"))
        text += " " + (paired_tpl.format(value=paired_str) if "{value}" in paired_tpl else paired_tpl)
    return text


def build_blocks(*, snapshot: dict | None, signals: dict | None,
                  grades: dict | None, brief_url: str | None = None,
                  run_url: str | None = None) -> list:
    """Compose Slack Block Kit payload blocks. Returns a list of blocks
    suitable for POSTing to an incoming webhook."""
    today = date.today()
    blocks: list = []

    # Header
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text",
                  "text": f"XFreight Morning Digest — {today:%a, %b %d, %Y}"}
    })

    # MTD section
    snap = snapshot or {}
    mtd_label = snap.get("mtd_label", "MTD")
    mtd_lines = [
        f"*Revenue ({mtd_label}):* {_money(snap.get('mtd_revenue'))}",
        f"*Margin:* {_money(snap.get('mtd_margin'))} ({_pct(snap.get('mtd_margin_pct'))})",
        f"*Loads:* {_num(snap.get('mtd_loads'))}  ·  *Miles:* {_num(snap.get('mtd_miles'))}",
    ]
    if snap.get("rpm_actual") is not None:
        # RPM gets 2 decimals — _money rounds to whole dollars which
        # turns $2.95 into "$3" and loses the goal-vs-actual nuance.
        try:
            actual = f"${float(snap['rpm_actual']):.2f}"
            goal = f"${float(snap.get('rpm_goal') or 0):.2f}" if snap.get("rpm_goal") else "—"
            mtd_lines.append(f"*RPM:* {actual}/mi  (goal {goal}/mi)")
        except (TypeError, ValueError):
            pass
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(mtd_lines)}
    })

    # Risk Watch
    risk_data = signals or {}
    risk_list = risk_data.get("signals") or []
    if risk_list:
        tripped = [s for s in risk_list if s.get("tripped")]
        ok_count = len(risk_list) - len(tripped)
        risk_text = [f"*Risk Watch* — {len(tripped)} tripped · {ok_count} ok"]
        for s in tripped[:5]:  # cap at 5 to keep digest scannable
            sev = (s.get("severity") or "medium").lower()
            emoji = {"high": ":red_circle:", "medium": ":large_orange_diamond:",
                     "low": ":large_yellow_circle:"}.get(sev, ":small_red_triangle:")
            risk_text.append(f"{emoji} *{s.get('title')}* — {_tripped_text(s)}")
        if len(tripped) > 5:
            risk_text.append(f"_…and {len(tripped) - 5} more tripped signals._")
        if not tripped:
            risk_text.append(":white_check_mark: All tracked risk signals within threshold.")
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(risk_text)}
        })

    # Decision Grades
    grade_data = grades or {}
    grade_list = grade_data.get("grades") or []
    if grade_list:
        counts = {"confirmed": 0, "mixed": 0, "wrong": 0, "pending": 0}
        for g in grade_list:
            k = g.get("grade", "pending")
            counts[k] = counts.get(k, 0) + 1
        decision_text = [
            "*Decisions graded*",
            f":white_check_mark: {counts['confirmed']} confirmed  ·  "
            f":large_orange_diamond: {counts['mixed']} mixed  ·  "
            f":x: {counts['wrong']} wrong  ·  "
            f":hourglass_flowing_sand: {counts['pending']} pending",
        ]
        # Surface the most recent non-pending grade for context.
        recent_graded = [g for g in grade_list if g.get("grade") != "pending"]
        recent_graded.sort(key=lambda g: g.get("journal_date", ""), reverse=True)
        if recent_graded:
            r = recent_graded[0]
            mark = {"confirmed": ":white_check_mark:", "mixed": ":large_orange_diamond:",
                    "wrong": ":x:"}.get(r.get("grade"), ":small_blue_diamond:")
            decision_text.append(
                f"_Most recent:_ {mark} *{r.get('title')}* ({r.get('journal_date', '?')})"
            )
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(decision_text)}
        })

    # Footer with links
    footer_parts = []
    if brief_url:
        footer_parts.append(f"<{brief_url}|Open full brief>")
    if run_url:
        footer_parts.append(f"<{run_url}|Workflow run>")
    if footer_parts:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "  ·  ".join(footer_parts)}]
        })

    return blocks


def post_to_webhook(blocks: list, webhook_url: str, fallback_text: str = "XFreight digest") -> bool:
    """POST Block Kit payload to an incoming webhook (Slack or Teams).
    Returns True on 2xx, False on any error."""
    payload = {"text": fallback_text, "blocks": blocks}
    try:
        resp = requests.post(webhook_url, json=payload, timeout=30)
        if 200 <= resp.status_code < 300:
            log.info("digest posted (HTTP %d)", resp.status_code)
            return True
        log.error("webhook returned HTTP %d: %s", resp.status_code, resp.text[:300])
        return False
    except Exception as exc:
        log.error("webhook post failed: %s", exc)
        return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="Post XFreight morning digest to Slack/Teams.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compose + print the payload, don't POST.")
    parser.add_argument("--brief-url", default=os.environ.get("BRIEF_URL"),
                        help="Optional link to the full brief.")
    parser.add_argument("--run-url", default=os.environ.get("RUN_URL"),
                        help="Optional link to the workflow run.")
    args = parser.parse_args(argv)

    snapshot = _latest_snapshot()
    signals = _onedrive_json("risk-watch-latest.json") or _read_json(_WIKI_DIR / "risk-watch-latest.json")
    grades = _onedrive_json("decision-grades.json") or _read_json(_WIKI_DIR / "decision-grades.json")

    if not any((snapshot, signals, grades)):
        log.warning("No source files found — nothing to digest. "
                    "Run the scorecard first so it writes its OneDrive snapshot "
                    "(Scorecard/snapshot-latest.json), or set AZURE_TENANT_ID/"
                    "CLIENT_ID/CLIENT_SECRET/ONEDRIVE_USER_UPN to read it.")
        return 0  # not an error; just nothing to post

    blocks = build_blocks(snapshot=snapshot, signals=signals, grades=grades,
                          brief_url=args.brief_url, run_url=args.run_url)

    if args.dry_run:
        print(json.dumps({"blocks": blocks}, indent=2))
        return 0

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        log.warning("SLACK_WEBHOOK_URL not set — digest composed but not posted. "
                    "Set the secret in GitHub Actions to enable delivery.")
        return 0

    ok = post_to_webhook(blocks, webhook,
                         fallback_text=f"XFreight digest — {date.today():%a %b %d}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
