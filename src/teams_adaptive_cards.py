"""Post per-owner Adaptive Cards to the Teams Safety & Compliance channel.

Reads output/accountability-{date}.json written by
safety_compliance_email.py and posts one full-width Adaptive Card per
owner (Audra first, then Jackson + Dan).

Each card is a read-only summary of today's action items with severity
badges, days-open carry-forward, and occurrence escalation flags.  Each
item has two buttons:
  📋 Record action — links to the main Microsoft Form (TEAMS_FORM_URL)
      where the owner logs coaching / corrective action taken.
  🚫 Dismiss — links to a lightweight dismiss form (TEAMS_DISMISS_FORM_URL)
      for false reports or non-issues. Pre-fills the same fields so the
      Power Automate flow can write a "Dismissed" row to Accountability
      Log.xlsx, which triggers the existing suppression pipeline and removes
      the item from tomorrow's card. The button is hidden when
      TEAMS_DISMISS_FORM_URL is not configured.

GitHub Secrets used:
  TEAMS_SAFETY_WEBHOOK      — incoming webhook URL
  TEAMS_FORM_URL            — Microsoft Form fill-in URL (optional; button
                              hidden when not set)
  TEAMS_DISMISS_FORM_URL    — Lightweight dismiss form URL (optional; button
                              hidden when not set)
"""

import datetime
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore

# ---------------------------------------------------------------------------
# Graph API — channel message management
# ---------------------------------------------------------------------------

_GRAPH = "https://graph.microsoft.com/v1.0"
_CARD_IDS_FOLDER = "Safety"
_CARD_IDS_FILE   = "teams-card-ids.json"


def _graph_token() -> "str | None":
    """Get a Graph API token using the existing Azure app credentials."""
    tid = os.environ.get("AZURE_TENANT_ID", "").strip()
    cid = os.environ.get("AZURE_CLIENT_ID", "").strip()
    sec = os.environ.get("AZURE_CLIENT_SECRET", "").strip()
    if not (tid and cid and sec) or _requests is None:
        return None
    try:
        r = _requests.post(
            f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": sec,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["access_token"]
    except Exception as exc:
        print(f"teams_adaptive_cards: could not get Graph token: {exc}")
        return None


def _load_card_ids(od_tok: str, upn: str) -> dict:
    """Load stored Teams message IDs from OneDrive. Returns {} on any error."""
    try:
        from src.onedrive_upload import download_file
        raw = download_file(od_tok, upn, f"{_CARD_IDS_FOLDER}/{_CARD_IDS_FILE}")
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _save_card_ids(od_tok: str, upn: str, ids: dict) -> None:
    """Persist message IDs to OneDrive so the next run can delete them."""
    try:
        from src.onedrive_upload import ensure_folder, upload_file
        ensure_folder(od_tok, upn, _CARD_IDS_FOLDER)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(ids, tf)
            tmp = Path(tf.name)
        upload_file(od_tok, upn, folder_path=_CARD_IDS_FOLDER,
                    filename=_CARD_IDS_FILE, file_path=tmp)
        tmp.unlink(missing_ok=True)
    except Exception as exc:
        print(f"teams_adaptive_cards: could not save card IDs: {exc}")


def _delete_cards(gtok: str, team_id: str, channel_id: str, ids: dict) -> None:
    """Soft-delete previous cards by stored message ID (shows 'message deleted')."""
    for label, msg_id in ids.items():
        try:
            r = _requests.delete(
                f"{_GRAPH}/teams/{team_id}/channels/{channel_id}/messages/{msg_id}",
                headers={"Authorization": f"Bearer {gtok}"},
                timeout=15,
            )
            if r.status_code in (200, 204):
                print(f"Deleted old {label} card (msg {msg_id})")
            else:
                print(f"Could not delete {label} card {msg_id}: HTTP {r.status_code}")
        except Exception as exc:
            print(f"Error deleting {label} card {msg_id}: {exc}")


def _trigger_pa_via_onedrive(od_tok: str, upn: str, card: dict, label: str) -> bool:
    """Write card JSON to OneDrive to trigger the Power Automate flow.

    PA watches Safety/pa-triggers/ for file changes (free standard connector).
    The flow handles deletion of the previous card and posting the new one.
    Returns True if the trigger file was written successfully.
    """
    filename = "teams-card-audra.json" if "AUDRA" in label.upper() else "teams-card-ops.json"
    try:
        from src.onedrive_upload import ensure_folder, upload_file
        ensure_folder(od_tok, upn, "Safety/pa-triggers")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump({"card": card, "_ts": datetime.datetime.utcnow().isoformat()}, tf)
            tmp = Path(tf.name)
        upload_file(od_tok, upn, folder_path="Safety/pa-triggers",
                    filename=filename, file_path=tmp)
        tmp.unlink(missing_ok=True)
        print(f"{label}: PA trigger file written → Safety/pa-triggers/{filename}")
        return True
    except Exception as exc:
        print(f"{label}: could not write PA trigger file: {exc}")
        return False


def _post_card_pa(pa_url: str, card: dict) -> bool:
    """POST an Adaptive Card to a Power Automate HTTP trigger. Returns True on success."""
    try:
        r = _requests.post(pa_url, json={"card": card}, timeout=45)
        if r.status_code in range(200, 300):
            return True
        print(f"PA flow returned HTTP {r.status_code}: {r.text[:300]}")
    except Exception as exc:
        print(f"PA flow post failed: {exc}")
    return False


def _post_card_graph(gtok: str, team_id: str, channel_id: str, card: dict) -> "str | None":
    """Post an Adaptive Card via Graph API. Returns the new message ID or None."""
    att_id  = uuid.uuid4().hex
    payload = {
        "body": {
            "contentType": "html",
            "content": f'<attachment id="{att_id}"></attachment>',
        },
        "attachments": [{
            "id": att_id,
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": json.dumps(card),
        }],
    }
    try:
        r = _requests.post(
            f"{_GRAPH}/teams/{team_id}/channels/{channel_id}/messages",
            headers={
                "Authorization": f"Bearer {gtok}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if r.status_code in (200, 201):
            return r.json().get("id")
        print(f"Graph post failed: HTTP {r.status_code} — {r.text[:400]}")
    except Exception as exc:
        print(f"Error posting card via Graph: {exc}")
    return None


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
        f"{_FF_OCCURRENCES}={item.get('occurrence', 1)}",
    ]

    owner_name = _OWNER_NAME.get(owner_label)
    if owner_name:
        params.insert(1, f"{_FF_NAME}={_qstr(owner_name)}")

    return base_url + "&" + "&".join(params)


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------

def _item_block(item: dict, form_url: str = "", dismiss_url: str = "") -> dict:
    """One Container block per accountability item with its own action buttons."""
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

    header = f"{emoji} **{cat}**"
    if actioned:
        header += "  ✅ Actioned"
    elif days >= 3:
        header += f"  ⚠️ Day {days} — ESCALATED"
    elif days > 1:
        header += f"  ↩ Day {days} open"
    if occ >= 3:
        header += f"  🚨 #{occ} in 30d"
    elif occ == 2:
        header += f"  ⚠️ 2nd in 30d"

    subject = (f"{drv} — " if drv else "") + detail

    block_items: list[dict] = [
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

    buttons: list[dict] = []
    if form_url:
        buttons.append({
            "type": "Action.OpenUrl",
            "title": "📋 Record action",
            "url": form_url,
            "style": "positive",
        })
    if dismiss_url:
        buttons.append({
            "type": "Action.OpenUrl",
            "title": "🚫 Dismiss",
            "url": dismiss_url,
            "style": "destructive",
        })
    if buttons:
        block_items.append({
            "type": "ActionSet",
            "spacing": "Small",
            "actions": buttons,
        })

    return {
        "type": "Container",
        "separator": True,
        "spacing": "Medium",
        "items": block_items,
    }


def build_owner_card(
    owner_label: str,
    items: list[dict],
    today: datetime.date,
    run_url: str = "",
    form_url: str = "",
    dismiss_url: str = "",
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
        item_url    = _prefill_url(form_url,    item, today, owner_label) if form_url    else ""
        dismiss_item_url = _prefill_url(dismiss_url, item, today, owner_label) if dismiss_url else ""
        body.append(_item_block(item, item_url, dismiss_item_url))

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
    dismiss_url: str = "",
) -> None:
    """Read accountability JSON and POST Adaptive Cards to Teams.

    Posting priority (first success wins):
      1. OneDrive trigger (TEAMS_PA_ONEDRIVE=1) — writes a JSON file that a
         Power Automate flow watches; PA handles delete-old + post-new using
         free standard connectors.
      2. Power Automate HTTP trigger (TEAMS_PA_URL_AUDRA / _OPS) — PA handles
         delete + post; requires premium PA license.
      3. Microsoft Graph API — posts directly and tracks message IDs; deletion
         requires ChannelMessage.ReadWrite.All (may not be available).
      4. Incoming webhook — no ID tracking, no cleanup.
    Silent no-op when no method is configured.
    """
    if _requests is None:
        print("requests library not available — skipping Teams posts.")
        return
    if not acc_path.exists():
        print(f"Accountability JSON not found at {acc_path} — skipping.")
        return

    pa_url_audra = os.environ.get("TEAMS_PA_URL_AUDRA", "").strip()
    pa_url_ops   = os.environ.get("TEAMS_PA_URL_OPS",   "").strip()
    use_pa_od    = os.environ.get("TEAMS_PA_ONEDRIVE", "").strip().lower() in ("1", "true", "yes")

    team_id    = os.environ.get("TEAMS_SAFETY_TEAM_ID", "").strip()
    channel_id = os.environ.get("TEAMS_SAFETY_CHANNEL_ID", "").strip()
    upn        = os.environ.get("ONEDRIVE_USER_UPN", "").strip()
    use_graph  = bool(team_id and channel_id and upn)

    # Acquire OneDrive token upfront — needed for OneDrive PA trigger and/or Graph cleanup.
    od_tok: "str | None" = None
    if (use_pa_od or use_graph) and upn:
        try:
            from src.onedrive_upload import get_token as _get_od_tok
            od_tok = _get_od_tok(
                os.environ.get("AZURE_TENANT_ID", ""),
                os.environ.get("AZURE_CLIENT_ID", ""),
                os.environ.get("AZURE_CLIENT_SECRET", ""),
            )
        except Exception as exc:
            print(f"teams_adaptive_cards: could not get OneDrive token: {exc}")

    # Graph token is only needed when Graph API posting is in scope.
    gtok    = _graph_token() if (use_graph and not use_pa_od and not pa_url_audra) else None
    new_ids: dict = {}

    # Graph cleanup runs only when no PA method is active.
    if use_graph and gtok and od_tok and not use_pa_od and not pa_url_audra:
        try:
            old_ids = _load_card_ids(od_tok, upn)
            if old_ids:
                print(f"Cleaning up {len(old_ids)} previous card(s) via Graph...")
                _delete_cards(gtok, team_id, channel_id, old_ids)
        except Exception as exc:
            print(f"Graph card cleanup skipped: {exc}")

    data  = json.loads(acc_path.read_text())
    today = datetime.date.fromisoformat(
        data.get("date", datetime.date.today().isoformat())
    )

    def _post(label: str, items: list[dict], pa_url: str = "") -> None:
        if not items:
            print(f"{label}: no action items today — skipping card.")
            return
        payload = build_owner_card(label, items, today, run_url, form_url, dismiss_url)
        if not payload:
            return
        card = payload["attachments"][0]["content"]

        # 1. OneDrive trigger — PA flow handles delete + post (free standard connectors)
        if use_pa_od and od_tok and upn:
            ok = _trigger_pa_via_onedrive(od_tok, upn, card, label)
            if ok:
                print(f"{label} card queued via OneDrive → PA flow ({len(items)} items)")
                return
            print(f"{label}: OneDrive PA trigger failed — falling back.")

        # 2. Power Automate HTTP trigger (requires premium PA license)
        if pa_url:
            ok = _post_card_pa(pa_url, card)
            if ok:
                print(f"{label} card posted via Power Automate HTTP ({len(items)} items)")
                return
            print(f"{label}: PA HTTP flow failed — falling back.")

        # 3. Graph API (post + track IDs; deletion requires ChannelMessage.ReadWrite.All)
        if use_graph and gtok:
            msg_id = _post_card_graph(gtok, team_id, channel_id, card)
            if msg_id:
                new_ids[label] = msg_id
                print(f"{label} card posted via Graph ({len(items)} items, msg {msg_id})")
                return
            print(f"{label}: Graph post failed — falling back to webhook.")

        # 4. Webhook (no ID tracking, no cleanup)
        if not webhook:
            print(f"{label}: no posting method available — skipping.")
            return
        resp = _requests.post(webhook, json=payload, timeout=30)
        print(f"{label} card (webhook): HTTP {resp.status_code} ({len(items)} items)")
        if resp.status_code not in range(200, 300):
            print(f"  Response body: {resp.text[:400]}")

    _post("AUDRA",         data.get("audra", []), pa_url_audra)
    _post("JACKSON + DAN", data.get("ops",   []), pa_url_ops)

    if new_ids and od_tok and upn:
        _save_card_ids(od_tok, upn, new_ids)
        print(f"Saved {len(new_ids)} card ID(s) → {_CARD_IDS_FILE}")


# ---------------------------------------------------------------------------
# Entry point (called from safety_compliance_email.yml)
# ---------------------------------------------------------------------------

def main() -> int:
    webhook     = os.environ.get("TEAMS_SAFETY_WEBHOOK", "").strip()
    run_url     = os.environ.get("RUN_URL", "").strip()
    form_url    = os.environ.get("TEAMS_FORM_URL", "").strip()
    dismiss_url = os.environ.get("TEAMS_DISMISS_FORM_URL", "").strip()
    # PA URLs are read inside post_adaptive_cards via os.environ directly.

    today = datetime.date.today()
    acc_path = Path(f"output/accountability-{today.isoformat()}.json")
    if not acc_path.exists():
        yesterday = today - datetime.timedelta(days=1)
        acc_path = Path(f"output/accountability-{yesterday.isoformat()}.json")

    if not acc_path.exists():
        print(f"No accountability JSON found for {today} — skipping Teams post.")
        return 0

    post_adaptive_cards(acc_path, webhook, run_url, form_url, dismiss_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
