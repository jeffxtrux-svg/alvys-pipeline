"""Post per-owner Adaptive Cards to the Teams Safety & Compliance channel.

Reads output/accountability-{date}.json written by
safety_compliance_email.py and posts one full-width Adaptive Card per
owner (Audra first, then Jackson + Dan).

Each card is a read-only summary of today's action items with severity
badges, days-open carry-forward, and occurrence escalation flags.  Each
item has its own "📋 Record action" button linking to a Microsoft Form
(TEAMS_FORM_URL) where the owner logs what they did; the form's Power
Automate flow writes a row into Accountability Log.xlsx in
OneDrive/Safety/ — no Premium license required.

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
from urllib.parse import quote
from zoneinfo import ZoneInfo

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
_SEV_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium"}

# ---------------------------------------------------------------------------
# Microsoft Forms pre-fill field IDs
# Extracted from the "Get Pre-filled URL" feature on 2026-06-17.
# ---------------------------------------------------------------------------

_FF_DATE        = "rd58e61abbff8482ea492899559281c0a"
_FF_NAME        = "r61a1c5b6d055470c95c0e2bbd7e4c5df"
_FF_DRIVER_UNIT = "rf58da9be72cf416f8770d9826822a3cf"
_FF_CATEGORY    = "reddebf51c37244608f4da3d764282741"
_FF_SEVERITY    = "rc954b19326974b1491b6e514d1be602c"
_FF_DETAIL      = "r1bf22e5124184daba438981e275b4947"
_FF_DAYS_OPEN   = "r0b3154b6b58b4f9590d0a404408bc7fb"
_FF_OCCURRENCES = "r6be0fbe806b84743995a97d5c3afde48"
# Action Taken and Notes are left blank for the owner to fill in.

# owner_label → form choice value (must match exactly)
_OWNER_NAME = {"AUDRA": "Audra"}  # JACKSON + DAN: left blank (two people share card)


def _prefill_url(
    base_url: str,
    item: dict,
    today: datetime.date,
    owner_label: str,
) -> str:
    """Return the base form URL with per-item fields pre-populated."""
    if not base_url:
        return base_url

    def _qstr(val: str) -> str:
        """Choice/date fields: wrap in JSON quotes then URL-encode."""
        return quote(f'"{val}"', safe="")

    def _qtxt(val: str) -> str:
        """Text fields: URL-encode without extra quotes."""
        return quote(val, safe="")

    sev = _SEV_LABEL.get(item.get("severity", "medium"), "Medium")
    drv = item.get("driver") or item.get("unit") or ""

    params: list[str] = [
        f"{_FF_DATE}={_qstr(today.isoformat())}",
        f"{_FF_CATEGORY}={_qstr(item.get('category', ''))}",
        f"{_FF_SEVERITY}={_qstr(sev)}",
        f"{_FF_DRIVER_UNIT}={_qtxt(drv)}",
        f"{_FF_DETAIL}={_qtxt(item.get('detail', ''))}",
        f"{_FF_DAYS_OPEN}={item.get('days_open', 1)}",
        f"{_FF_OCCURRENCES}={item.get('_recurrence_count') or item.get('occurrence', 1)}",
    ]

    owner_name = _OWNER_NAME.get(owner_label)
    if owner_name:
        params.insert(1, f"{_FF_NAME}={_qstr(owner_name)}")

    return base_url + "&" + "&".join(params)


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------

def _item_block(item: dict, form_url: str = "") -> dict:
    """One Container block per accountability item with its own action button."""
    sev    = item.get("severity", "medium")
    emoji  = _SEV_EMOJI.get(sev, "🟡")
    color  = _SEV_COLOR.get(sev, "Accent")
    cat    = item.get("category", "")
    drv    = item.get("driver") or item.get("unit") or ""
    detail = item.get("detail", "")
    prompt = item.get("prompt", "")
    days   = item.get("days_open", 1)
    occ    = item.get("occurrence", 1)

    actioned = item.get("actioned_yesterday", False)

    if actioned:
        # Green completed block — no Record action button, dimmed text
        header = f"✅ ~~{cat}~~" if cat else "✅ Completed"
        subject = (f"{drv} — " if drv else "") + detail
        block_items: list[dict] = [
            {
                "type": "TextBlock",
                "text": header,
                "wrap": True,
                "weight": "Bolder",
                "color": "Good",
            },
            {
                "type": "TextBlock",
                "text": subject,
                "wrap": True,
                "spacing": "None",
                "isSubtle": True,
            },
            {
                "type": "TextBlock",
                "text": "✅ Action recorded",
                "wrap": True,
                "isSubtle": True,
                "spacing": "Small",
                "color": "Good",
                "size": "Small",
            },
        ]
        return {
            "type": "Container",
            "style": "good",
            "separator": True,
            "spacing": "Medium",
            "items": block_items,
        }

    is_coaching = "coaching needed" in cat.lower()
    rec_count   = item.get("_recurrence_count", 0)
    first_days  = item.get("_first_seen_days", days)

    # Normal open item
    header = f"{emoji} **{cat}**"
    # Day-open indicator (coaching gets a stronger escalation at day 5)
    if is_coaching and first_days >= 5:
        header += f"  🔴 Day {first_days} — Supervisor follow-up required"
    elif days >= 3:
        header += f"  ⚠️ Day {days} — ESCALATED"
    elif days > 1:
        header += f"  ↩ Day {days} open"
    # 30-day occurrence badge
    if occ >= 3:
        header += f"  🚨 #{occ} in 30d"
    elif occ == 2:
        header += f"  ⚠️ 2nd in 30d"
    # 90-day chronic pattern badge — overrides 30d badge when triggered
    if rec_count >= 3:
        header += f"  🔁 {rec_count}x in 90d — Progressive discipline"

    subject = (f"{drv} — " if drv else "") + detail

    block_items = [
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
    ]

    if form_url:
        block_items.append({
            "type": "ActionSet",
            "spacing": "Small",
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": "📋 Record action",
                    "url": form_url,
                    "style": "positive",
                }
            ],
        })

    return {
        "type": "Container",
        "separator": True,
        "spacing": "Medium",
        "items": block_items,
    }


def _all_clear_card(
    owner_label: str,
    today: datetime.date,
    suppressed_count: int,
    run_url: str = "",
) -> dict:
    """Return a compact 'all clear' card when every item was actioned yesterday."""
    body: list[dict] = [
        {
            "type": "Container",
            "style": "good",
            "bleed": True,
            "items": [
                {
                    "type": "TextBlock",
                    "text": f"✅ {owner_label} — Safety Accountability",
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
                    "text": f"All {suppressed_count} item(s) from yesterday were actioned — no new items today.",
                    "color": "Light",
                    "spacing": "None",
                    "wrap": True,
                },
            ],
        }
    ]
    actions: list[dict] = []
    if run_url:
        actions.append({"type": "Action.OpenUrl", "title": "View workflow run", "url": run_url})
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
        "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                         "contentUrl": None, "content": card}],
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

    actioned_items = [i for i in items if i.get("actioned_yesterday")]
    open_items     = [i for i in items if not i.get("actioned_yesterday")]

    # All clear — every item was actioned
    if not open_items:
        return _all_clear_card(owner_label, today, len(actioned_items), run_url)

    # Open items sorted by urgency; actioned items appended at the bottom
    sorted_open = sorted(
        open_items,
        key=lambda i: (-i.get("days_open", 1),
                       _SEV_RANK.get(i.get("severity", "medium"), 2)),
    )
    sorted_items = sorted_open + actioned_items

    n_open   = len(open_items)
    n_done   = len(actioned_items)
    new_cnt  = sum(1 for i in open_items if i.get("days_open", 1) == 1)
    cf_cnt   = sum(1 for i in open_items if i.get("days_open", 1) > 1)
    esc_cnt  = sum(1 for i in open_items if i.get("days_open", 1) >= 3)

    parts = [f"{n_open} open"]
    if new_cnt:
        parts.append(f"{new_cnt} new today")
    if cf_cnt:
        parts.append(f"{cf_cnt} carried forward")
    if esc_cnt:
        parts.append(f"⚠️ {esc_cnt} escalated (3+ days open)")
    if n_done:
        parts.append(f"✅ {n_done} completed")
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
        # Don't show "Record action" button on already-completed items
        if item.get("actioned_yesterday"):
            body.append(_item_block(item, ""))
        else:
            item_url = _prefill_url(form_url, item, today, owner_label) if form_url else ""
            body.append(_item_block(item, item_url))

    actions: list[dict] = []
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
    resolved_today: "set[str] | None" = None,
) -> None:
    """Read accountability JSON and POST Adaptive Cards to Teams webhook.

    resolved_today: category names (case-insensitive) actioned today.
    Matching items get the ✅ Actioned badge without waiting for tomorrow.
    """
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

    resolved_norm = {c.lower() for c in (resolved_today or set())}

    def _apply_resolved(items: list[dict]) -> list[dict]:
        if not resolved_norm:
            return items
        result = []
        for item in items:
            item = dict(item)
            cat = item.get("category", "").lower()
            drv = (item.get("driver") or item.get("unit") or "").lower()
            if (cat in resolved_norm or
                    (drv and f"driver:{drv}" in resolved_norm)):
                item["actioned_yesterday"] = True
            result.append(item)
        return result

    def _post(label: str, items: list[dict]) -> None:
        items = _apply_resolved(items)
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

    today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
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
