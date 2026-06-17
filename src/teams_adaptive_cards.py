"""Post per-owner Adaptive Cards to the Teams Safety & Compliance channel.

Reads output/safety-accountability-{date}.json written by
safety_compliance_email.py and posts one full-width Adaptive Card per
owner (Audra first, then Jackson + Dan).

Adaptive Cards vs the old MessageCard:
  - Rich visual hierarchy: colored headers, per-item containers, severity
    color coding, day-open badges.
  - Per-item action dropdowns scoped to the category (DOT inspection items
    get scheduling choices; safety events get coaching choices, etc.).
  - Action.Http submit button POSTs structured JSON to a Power Automate
    HTTP trigger (TEAMS_RESPONSE_WEBHOOK) so responses are logged to
    OneDrive automatically.  Falls back to Action.OpenUrl (workflow run
    link) when the secret is not set.
  - msteams.width="Full" so the card spans the full channel width on
    both desktop and mobile.

GitHub Secrets used:
  TEAMS_SAFETY_WEBHOOK    — incoming webhook URL (existing)
  TEAMS_RESPONSE_WEBHOOK  — Power Automate HTTP trigger URL (optional;
                            enables structured response capture)
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
# Category-specific action choices
# Shown in the per-item ChoiceSet so Audra / Jackson+Dan pick what they did.
# ---------------------------------------------------------------------------

def _choices_for(category: str) -> list[dict]:
    cat = category.lower()
    if "dot inspection" in cat:
        return [
            {"title": "Inspection scheduled — date set",  "value": "insp_scheduled"},
            {"title": "Inspection scheduled — date TBD",  "value": "insp_scheduled_tbd"},
            {"title": "Inspection completed",             "value": "insp_completed"},
            {"title": "Unit deadlined / out of service",  "value": "deadlined"},
            {"title": "Escalated to JB",                  "value": "escalated_jb"},
            {"title": "Not yet actioned",                 "value": "pending"},
        ]
    if "safety event" in cat and "disposition" in cat:
        return [
            {"title": "Coached in Samsara",           "value": "coached_samsara"},
            {"title": "Coached in person",            "value": "coached_person"},
            {"title": "Verbal warning issued",        "value": "verbal_warning"},
            {"title": "Written warning issued",       "value": "written_warning"},
            {"title": "Dismissed — not driver fault", "value": "dismissed"},
            {"title": "Escalated to JB",              "value": "escalated_jb"},
            {"title": "Not yet actioned",             "value": "pending"},
        ]
    if "safety event" in cat or "coached" in cat:
        return [
            {"title": "Coaching completed in Samsara", "value": "coached_samsara"},
            {"title": "Coaching completed in person",  "value": "coached_person"},
            {"title": "Written warning issued",        "value": "written_warning"},
            {"title": "Escalated to JB",               "value": "escalated_jb"},
            {"title": "Not yet actioned",              "value": "pending"},
        ]
    if "hos violation" in cat:
        return [
            {"title": "Driver counseled",        "value": "counseled"},
            {"title": "Verbal warning issued",   "value": "verbal_warning"},
            {"title": "Written warning issued",  "value": "written_warning"},
            {"title": "Escalated to JB",         "value": "escalated_jb"},
            {"title": "Not yet actioned",        "value": "pending"},
        ]
    if "dvir compliance" in cat:
        return [
            {"title": "Driver notified to complete inspections", "value": "notified"},
            {"title": "Driver counseled",                        "value": "counseled"},
            {"title": "Written warning issued",                  "value": "written_warning"},
            {"title": "Not yet actioned",                        "value": "pending"},
        ]
    if "prior day logs" in cat:
        return [
            {"title": "Driver notified to certify logs", "value": "notified"},
            {"title": "Driver counseled",                "value": "counseled"},
            {"title": "Not yet actioned",                "value": "pending"},
        ]
    if "cdl" in cat:
        return [
            {"title": "Renewal appointment scheduled", "value": "scheduled"},
            {"title": "Renewal completed",             "value": "completed"},
            {"title": "Driver pulled from dispatch",   "value": "pulled"},
            {"title": "Escalated to JB",               "value": "escalated_jb"},
            {"title": "Not yet actioned",              "value": "pending"},
        ]
    if "med card" in cat:
        return [
            {"title": "DOT physical scheduled", "value": "scheduled"},
            {"title": "DOT physical completed", "value": "completed"},
            {"title": "Driver pulled from dispatch", "value": "pulled"},
            {"title": "Escalated to JB",            "value": "escalated_jb"},
            {"title": "Not yet actioned",           "value": "pending"},
        ]
    if "disqualified" in cat:
        return [
            {"title": "Driver pulled from dispatch", "value": "pulled"},
            {"title": "Termination initiated",       "value": "terminated"},
            {"title": "Escalated to JB",             "value": "escalated_jb"},
            {"title": "Not yet actioned",            "value": "pending"},
        ]
    if "dvir defect" in cat:
        return [
            {"title": "Defect repaired — cleared in Samsara", "value": "repaired"},
            {"title": "Repair scheduled",                     "value": "repair_scheduled"},
            {"title": "Unit taken out of service",            "value": "out_of_service"},
            {"title": "Not yet actioned",                     "value": "pending"},
        ]
    if "low safety score" in cat or "speeding" in cat:
        return [
            {"title": "Coaching completed",      "value": "coached"},
            {"title": "Verbal warning issued",   "value": "verbal_warning"},
            {"title": "Written warning issued",  "value": "written_warning"},
            {"title": "Improvement plan set",    "value": "plan_set"},
            {"title": "Escalated to JB",         "value": "escalated_jb"},
            {"title": "Not yet actioned",        "value": "pending"},
        ]
    # Default
    return [
        {"title": "Actioned — see notes", "value": "actioned"},
        {"title": "Driver notified",      "value": "notified"},
        {"title": "Escalated to JB",      "value": "escalated_jb"},
        {"title": "Not yet actioned",     "value": "pending"},
    ]


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------

def _item_block(item: dict, idx: int) -> dict:
    """One Container block per accountability item with choice input."""
    sev    = item.get("severity", "medium")
    emoji  = _SEV_EMOJI.get(sev, "🟡")
    color  = _SEV_COLOR.get(sev, "Accent")
    cat    = item.get("category", "")
    drv    = item.get("driver") or item.get("unit") or ""
    detail = item.get("detail", "")
    prompt = item.get("prompt", "")
    days   = item.get("days_open", 1)

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
            {
                "type": "Input.ChoiceSet",
                "id": f"action_{idx}",
                "placeholder": "Select action taken…",
                "value": "pending",
                "choices": _choices_for(cat),
                "spacing": "Small",
            },
        ],
    }


def build_owner_card(
    owner_label: str,
    items: list[dict],
    today: datetime.date,
    run_url: str = "",
    response_webhook: str = "",
) -> dict:
    """Return the full Teams Adaptive Card payload for one owner."""
    if not items:
        return {}

    sev_rank = _SEV_RANK
    sorted_items = sorted(
        items,
        key=lambda i: (-i.get("days_open", 1),
                       sev_rank.get(i.get("severity", "medium"), 2)),
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

    # Header
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

    # Per-item blocks
    for idx, item in enumerate(sorted_items):
        body.append(_item_block(item, idx))

    # General notes input
    body.append({
        "type": "Input.Text",
        "id": "notes",
        "label": "Notes / next steps",
        "placeholder": "Dates, contacts, follow-up actions, escalations…",
        "isMultiline": True,
        "spacing": "Large",
        "separator": True,
    })

    # Build Action.Http body template — references each per-item input.
    # Teams substitutes ${input_id} with the user's selection before POSTing.
    action_entries = ", ".join(
        f'"item_{idx}": {{"category": {json.dumps(it.get("category",""))}, '
        f'"driver": {json.dumps(it.get("driver") or it.get("unit") or "")}, '
        f'"action": "${{{f"action_{idx}"}}}"}}'
        for idx, it in enumerate(sorted_items)
    )
    http_body = (
        f'{{"owner": {json.dumps(owner_label)}, '
        f'"date": "{today.isoformat()}", '
        f'"notes": "${{notes}}", '
        f'"items": {{{action_entries}}}}}'
    )

    actions: list[dict] = []
    if response_webhook:
        actions.append({
            "type": "Action.Http",
            "title": "✓ Submit actions",
            "method": "POST",
            "url": response_webhook,
            "headers": [{"name": "Content-Type", "value": "application/json"}],
            "body": http_body,
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
    response_webhook: str = "",
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
        payload = build_owner_card(label, items, today, run_url, response_webhook)
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
    webhook          = os.environ.get("TEAMS_SAFETY_WEBHOOK", "").strip()
    run_url          = os.environ.get("RUN_URL", "").strip()
    response_webhook = os.environ.get("TEAMS_RESPONSE_WEBHOOK", "").strip()

    today = datetime.date.today()
    acc_path = Path(f"output/safety-accountability-{today.isoformat()}.json")
    if not acc_path.exists():
        # One-day fallback for timezone edge cases
        yesterday = today - datetime.timedelta(days=1)
        acc_path = Path(f"output/safety-accountability-{yesterday.isoformat()}.json")

    if not acc_path.exists():
        print(f"No accountability JSON found for {today} — skipping Teams post.")
        return 0

    post_adaptive_cards(acc_path, webhook, run_url, response_webhook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
