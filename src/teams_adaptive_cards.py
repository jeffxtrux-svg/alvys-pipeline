"""Post per-owner Adaptive Cards to the Teams Safety & Compliance channel.

Reads output/accountability-{date}.json written by
safety_compliance_email.py and posts one full-width Adaptive Card per
owner (Audra first, then Jackson + Dan).

Each card is a read-only summary of today's action items with severity
badges, days-open carry-forward, and occurrence escalation flags.  A
"📋 Record an action" button links to a Microsoft Form (TEAMS_FORM_URL)
where the owner logs what they did; the form's Power Automate flow
writes a row into Accountability Log.xlsx in OneDrive/Safety/ — no
Premium license required.

GitHub Secrets used:
  TEAMS_SAFETY_WEBHOOK  — incoming webhook URL
  TEAMS_FORM_URL        — Microsoft Form fill-in URL (optional; button
                          is hidden when not set)
"""

import datetime
import json
import os
import sys
from pathlib import Path

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEV_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡"}
_SEV_COLOR = {"critical": "Attention", "high": "Warning", "medium": "Accent"}
_SEV_RANK  = {"critical": 0, "high": 1, "medium": 2}


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------

def _item_block(item: dict) -> dict:
    """One Container block per accountability item (read-only)."""
    sev    = item.get("severity", "medium")
    emoji  = _SEV_EMOJI.get(sev, "🟡")
    color  = _SEV_COLOR.get(sev, "Accent")
    cat    = item.get("category", "")
    drv    = item.get("driver") or item.get("unit") or ""
    detail = item.get("detail", "")
    prompt = item.get("prompt", "")
    days   = item.get("days_open", 1)
    occ    = item.get("occurrence", 1)

    occ = item.get("occurrence", 1)

    occ = item.get("occurrence", 1)

    header = f"{emoji} **{cat}**"
    if days >= 3:
        header += f"  ⚠️ Day {days} — ESCALATED"
    elif days > 1:
        header += f"  ↩ Day {days} open"
    if occ >= 3:
        header += f"  🚨 #{occ} in 30d"
    elif occ == 2:
        header += f"  ⚠️ 2nd in 30d"

    subject = (f"{drv} — " if drv else "") + detail

    return {
        "type": "Container",
        "separator": True,
        "spacing": "Medium",
        "items": [
            {
                "type": "TextBlock",
                "text": header,
                "wrap": True,
                "weight": "Bolder",
                "color": color,
            },
            {
                "type": "TextBlock",
                "text": subject,
                "wrap": True,
                "spacing": "None",
            },
            {
                "type": "TextBlock",
                "text": f"→ _{prompt}_",
                "wrap": True,
                "isSubtle": True,
                "spacing": "Small",
                "color": "Default",
            },
        ],
    }


def build_owner_card(
    owner_label: str,
    items: list[dict],
    today: datetime.date,
    run_url: str = "",
    form_url: str = "",
) -> dict:
    """Return the full Teams Adaptive Card payload for one owner."""
    if not items:
        return {}

    sorted_items = sorted(
        items,
        key=lambda i: (-i.get("days_open", 1),
                       _SEV_RANK.get(i.get("severity", "medium"), 2)),
    )

    n        = len(items)
    new_cnt  = sum(1 for i in items if i.get("days_open", 1) == 1)
    cf_cnt   = sum(1 for i in items if i.get("days_open", 1) > 1)
    esc_cnt  = sum(1 for i in items if i.get("days_open", 1) >= 3)

    parts = [f"{n} action item(s)"]
    if new_cnt:
        parts.append(f"{new_cnt} new today")
    if cf_cnt:
        parts.append(f"{cf_cnt} carried forward")
    if esc_cnt:
        parts.append(f"⚠️ {esc_cnt} escalated (3+ days open)")
    subtitle = " · ".join(parts)

    body: list[dict] = [
        {
            "type": "Container",
            "style": "emphasis",
            "bleed": True,
            "items": [
                {
                    "type": "TextBlock",
                    "text": f"📋 {owner_label} — Safety Accountability",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Light",
                    "wrap": True,
                },
                {
                    "type": "TextBlock",
                    "text": today.strftime("%A, %B %-d, %Y"),
                    "color": "Light",
                    "spacing": "None",
                    "isSubtle": True,
                },
                {
                    "type": "TextBlock",
                    "text": subtitle,
                    "color": "Light",
                    "spacing": "None",
                    "isSubtle": True,
                    "wrap": True,
                },
            ],
        }
    ]

    for item in sorted_items:
        body.append(_item_block(item))

    actions: list[dict] = []
    if form_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "📋 Record an action",
            "url": form_url,
            "style": "positive",
        })
    if run_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "View workflow run",
            "url": run_url,
        })

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "actions": actions,
        "msteams": {"width": "Full"},
    }

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Post helpers
# ---------------------------------------------------------------------------

def post_adaptive_cards(
    acc_path: Path,
    webhook: str,
    run_url: str = "",
    form_url: str = "",
) -> None:
    """Read accountability JSON and POST Adaptive Cards to Teams webhook."""
    if not webhook:
        print("TEAMS_SAFETY_WEBHOOK not set — skipping Teams posts.")
        return
    if _requests is None:
        print("requests library not available — skipping Teams posts.")
        return
    if not acc_path.exists():
        print(f"Accountability JSON not found at {acc_path} — skipping.")
        return

    data  = json.loads(acc_path.read_text())
    today = datetime.date.fromisoformat(
        data.get("date", datetime.date.today().isoformat())
    )

    def _post(label: str, items: list[dict]) -> None:
        if not items:
            print(f"{label}: no action items today — skipping card.")
            return
        payload = build_owner_card(label, items, today, run_url, form_url)
        if not payload:
            return
        resp = _requests.post(webhook, json=payload, timeout=30)
        print(f"{label} card: HTTP {resp.status_code} ({len(items)} items)")
        if resp.status_code not in range(200, 300):
            print(f"  Response body: {resp.text[:400]}")

    _post("AUDRA", data.get("audra", []))
    _post("JACKSON + DAN", data.get("ops", []))


# ---------------------------------------------------------------------------
# Entry point (called from safety_compliance_email.yml)
# ---------------------------------------------------------------------------

def main() -> int:
    webhook  = os.environ.get("TEAMS_SAFETY_WEBHOOK", "").strip()
    run_url  = os.environ.get("RUN_URL", "").strip()
    form_url = os.environ.get("TEAMS_FORM_URL", "").strip()

    today = datetime.date.today()
    acc_path = Path(f"output/accountability-{today.isoformat()}.json")
    if not acc_path.exists():
        yesterday = today - datetime.timedelta(days=1)
        acc_path = Path(f"output/accountability-{yesterday.isoformat()}.json")

    if not acc_path.exists():
        print(f"No accountability JSON found for {today} — skipping Teams post.")
        return 0

    post_adaptive_cards(acc_path, webhook, run_url, form_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
