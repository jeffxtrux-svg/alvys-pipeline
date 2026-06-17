"""Post an end-of-day accountability summary card to Teams at ~5 pm CT.

Reads today's accountability JSON (output/ or OneDrive/Safety/) and
Accountability Log.xlsx to report which items were actioned vs. still open.

GitHub Secrets used:
  TEAMS_SAFETY_WEBHOOK  — same incoming webhook as the morning cards
  AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
  ONEDRIVE_USER_UPN
"""

from __future__ import annotations

import datetime
import io
import json
import os
import sys
from pathlib import Path

import pandas as pd

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore

from src.onedrive_upload import download_file, get_token

_ACC_FOLDER = "Safety"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_today_items(tok: str, upn: str, today: datetime.date) -> dict:
    """Return today's accountability JSON as a dict (audra/ops lists)."""
    local = Path(f"output/accountability-{today.isoformat()}.json")
    if local.exists():
        try:
            return json.loads(local.read_text())
        except Exception:
            pass
    try:
        raw = download_file(tok, upn, f"{_ACC_FOLDER}/accountability-{today.isoformat()}.json")
        return json.loads(raw)
    except Exception:
        return {}


def _load_log_entries(tok: str, upn: str, today: datetime.date) -> list[dict]:
    """Return rows from Accountability Log.xlsx logged on today's date."""
    entries: list[dict] = []
    try:
        raw = download_file(tok, upn, f"{_ACC_FOLDER}/Accountability Log.xlsx")
        xl  = pd.ExcelFile(io.BytesIO(raw))
        df  = xl.parse(xl.sheet_names[0])
        df.columns = [str(c).strip().lower() for c in df.columns]
        date_col = next((c for c in df.columns if "date" in c), None)
        if date_col is None:
            return entries
        for _, row in df.iterrows():
            raw_date = row[date_col]
            if pd.isna(raw_date):
                continue
            try:
                row_date = pd.Timestamp(raw_date).date()
            except Exception:
                continue
            if row_date == today:
                entries.append({k: (None if pd.isna(v) else str(v).strip())
                                 for k, v in row.items()})
    except Exception as exc:
        print(f"Could not read Accountability Log.xlsx: {exc}")
    return entries


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _match(items: list[dict], log_entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split items into (actioned, still_open) by matching category."""
    cat_col = next(
        (k for k in (log_entries[0].keys() if log_entries else []) if "category" in k),
        "category",
    )
    name_col = next(
        (k for k in (log_entries[0].keys() if log_entries else []) if "name" in k),
        None,
    )
    action_col = next(
        (k for k in (log_entries[0].keys() if log_entries else []) if "action" in k),
        None,
    )

    # Map normalized category → log entry (last one wins if multiple)
    by_cat: dict[str, dict] = {}
    for e in log_entries:
        cat = (e.get(cat_col) or "").lower().strip()
        if cat:
            by_cat[cat] = e

    actioned: list[dict] = []
    still_open: list[dict] = []
    for item in items:
        cat_norm = (item.get("category") or "").lower().strip()
        if cat_norm in by_cat:
            entry = by_cat[cat_norm]
            copy = dict(item)
            copy["_logged_by"]     = entry.get(name_col) if name_col else None
            copy["_action_taken"]  = entry.get(action_col) if action_col else None
            actioned.append(copy)
        else:
            still_open.append(item)

    return actioned, still_open


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------

_SEV_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡"}


def _item_row(item: dict, done: bool) -> dict:
    cat  = item.get("category", "")
    drv  = item.get("driver") or item.get("unit") or ""
    sev  = item.get("severity", "medium")
    emoji = _SEV_EMOJI.get(sev, "🟡")
    prefix = "✅" if done else "❌"
    label  = f"{prefix} {emoji} **{cat}**" + (f" — {drv}" if drv else "")
    block: dict = {"type": "TextBlock", "text": label, "wrap": True, "spacing": "Small"}
    if done:
        by     = item.get("_logged_by") or ""
        action = item.get("_action_taken") or ""
        sub_parts = []
        if by:
            sub_parts.append(by)
        if action:
            sub_parts.append(action)
        if sub_parts:
            block["isSubtle"] = True
    return block


def build_eod_card(
    owner_label: str,
    actioned: list[dict],
    still_open: list[dict],
    today: datetime.date,
    run_url: str = "",
) -> dict:
    """Return Teams payload for the EOD summary card for one owner."""
    all_items = actioned + still_open
    if not all_items:
        return {}

    n_done = len(actioned)
    n_open = len(still_open)
    n_total = n_done + n_open

    if n_open == 0:
        headline = f"✅ All {n_total} item(s) actioned today"
        header_style = "good"
    elif n_done == 0:
        headline = f"❌ {n_open} item(s) still open — no actions recorded"
        header_style = "attention"
    else:
        headline = f"✅ {n_done} actioned · ❌ {n_open} still open"
        header_style = "warning"

    body: list[dict] = [
        {
            "type": "Container",
            "style": "emphasis",
            "bleed": True,
            "items": [
                {
                    "type": "TextBlock",
                    "text": f"📊 {owner_label} — End-of-Day Check",
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
                    "text": headline,
                    "color": "Light",
                    "spacing": "None",
                    "wrap": True,
                },
            ],
        }
    ]

    if actioned:
        body.append({
            "type": "TextBlock",
            "text": "**Actioned today:**",
            "weight": "Bolder",
            "spacing": "Medium",
        })
        for item in actioned:
            body.append(_item_row(item, done=True))
            by     = item.get("_logged_by") or ""
            action = item.get("_action_taken") or ""
            parts  = [p for p in [by, action] if p]
            if parts:
                body.append({
                    "type": "TextBlock",
                    "text": "  " + " — ".join(parts),
                    "wrap": True,
                    "isSubtle": True,
                    "spacing": "None",
                    "size": "Small",
                })

    if still_open:
        body.append({
            "type": "TextBlock",
            "text": "**Still open — no action recorded:**",
            "weight": "Bolder",
            "spacing": "Medium",
            "color": "Attention",
        })
        for item in still_open:
            body.append(_item_row(item, done=False))

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
# Post
# ---------------------------------------------------------------------------

def post_eod_summary(
    tok: str,
    upn: str,
    webhook: str,
    today: datetime.date,
    run_url: str = "",
) -> None:
    if not webhook:
        print("TEAMS_SAFETY_WEBHOOK not set — skipping EOD summary.")
        return
    if _requests is None:
        print("requests not available — skipping EOD summary.")
        return

    acc = _load_today_items(tok, upn, today)
    if not acc:
        print(f"No accountability JSON for {today} — skipping EOD summary.")
        return

    log_entries = _load_log_entries(tok, upn, today)
    print(f"Log entries for {today}: {len(log_entries)}")

    audra_all = acc.get("audra", [])
    ops_all   = acc.get("ops", [])

    def _post(label: str, items: list[dict]) -> None:
        if not items:
            return
        actioned, still_open = _match(items, log_entries)
        payload = build_eod_card(label, actioned, still_open, today, run_url)
        if not payload:
            return
        resp = _requests.post(webhook, json=payload, timeout=30)
        print(f"{label} EOD card: HTTP {resp.status_code} "
              f"({len(actioned)} actioned, {len(still_open)} open)")
        if resp.status_code not in range(200, 300):
            print(f"  Response body: {resp.text[:400]}")

    _post("AUDRA", audra_all)
    _post("JACKSON + DAN", ops_all)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    webhook = os.environ.get("TEAMS_SAFETY_WEBHOOK", "").strip()
    run_url = os.environ.get("RUN_URL", "").strip()

    tenant  = os.environ.get("AZURE_TENANT_ID", "").strip()
    client  = os.environ.get("AZURE_CLIENT_ID", "").strip()
    secret  = os.environ.get("AZURE_CLIENT_SECRET", "").strip()
    upn     = os.environ.get("ONEDRIVE_USER_UPN", "").strip()

    if not all([tenant, client, secret, upn]):
        print("Missing Azure credentials — cannot load OneDrive data.")
        return 1

    tok   = get_token(tenant, client, secret)
    today = datetime.date.today()

    post_eod_summary(tok, upn, webhook, today, run_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
