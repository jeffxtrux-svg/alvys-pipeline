"""
Weekly Safety Accountability Pattern Report.

Reads the last 7 daily accountability JSON files from OneDrive
(Safety/accountability-{date}.json) and emails + posts a Teams summary
card covering: top offenders, category breakdown, chronic items (5+
days open), resolution rate, and escalation flags.

Run: python -m src.accountability_weekly_report
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sys
from collections import defaultdict
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from src.onedrive_upload import get_token
from src.scorecard_email import send_email

load_dotenv()
log = logging.getLogger("accountability_weekly_report")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

GRAPH = "https://graph.microsoft.com/v1.0"
XFREIGHT_RED = "#B01C2E"
INK = "#1A1A2E"


# ---------------------------------------------------------------------------
# Key helpers (mirrors safety_compliance_email._accountability_key)
# ---------------------------------------------------------------------------

def _accountability_key(item):
    cat  = (item.get("category") or "").lower().strip()
    drv  = (item.get("driver") or "").lower().strip()
    unit = (item.get("unit") or "").lower().strip()
    if "dvir defect" in cat:
        detail = (item.get("detail") or "").lower().strip()
        return f"{cat}|{drv or unit}|{detail}"
    if "needs disposition" in cat:
        detail = (item.get("detail") or "").lower().strip()
        return f"{cat}|{drv}|{detail}"
    return f"{cat}|{drv or unit}"


def _subject_label(item):
    return item.get("driver") or item.get("unit") or "(unknown)"


# ---------------------------------------------------------------------------
# Download one day's JSON from OneDrive — fail soft on 404
# ---------------------------------------------------------------------------

def _download_day(tok, upn, date):
    user_enc = quote(upn, safe="@.")
    path = f"Safety/accountability-{date.isoformat()}.json"
    path_enc = "/".join(quote(p, safe="") for p in path.split("/"))
    url = f"{GRAPH}/users/{user_enc}/drive/root:/{path_enc}:/content"
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            log.warning("No accountability file for %s (404 — skipping)", date.isoformat())
            return None
        log.warning("Download failed for %s [%s]: %s",
                    date.isoformat(), resp.status_code, resp.text[:200])
        return None
    except Exception as exc:
        log.warning("Download error for %s: %s", date.isoformat(), exc)
        return None


# ---------------------------------------------------------------------------
# Load 7 days of data
# ---------------------------------------------------------------------------

def _load_week(tok, upn, today):
    """
    Returns list of (date, flat_items) for the 7 days before today.
    today-1 is "yesterday" (most recent), today-7 is "oldest".
    """
    days = []
    for offset in range(1, 8):
        d = today - datetime.timedelta(days=offset)
        data = _download_day(tok, upn, d)
        if data is None:
            continue
        items = list(data.get("audra") or []) + list(data.get("ops") or [])
        days.append((d, items))
    return days  # newest first (offset 1 → 7)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _analyse(days):
    """
    days: list of (date, [items]) newest-first.

    Returns dict with keys:
      yesterday_items, oldest_items, yesterday_date, oldest_date,
      top_offenders, category_breakdown, chronic_items,
      resolved_count, total_old, escalation_items,
      total_item_days, unique_subjects
    """
    if not days:
        return None

    yesterday_date, yesterday_items = days[0]
    oldest_date, oldest_items = days[-1]

    # Build a key→{days_appeared, max_days_open, max_occurrence, name, category} map
    subject_stats = {}
    for date, items in days:
        seen_keys_today = set()
        for item in items:
            key = _accountability_key(item)
            if key in seen_keys_today:
                continue
            seen_keys_today.add(key)
            name = _subject_label(item)
            cat  = item.get("category", "")
            if key not in subject_stats:
                subject_stats[key] = {
                    "name": name,
                    "category": cat,
                    "days_appeared": 0,
                    "max_days_open": 0,
                    "max_occurrence": 0,
                }
            s = subject_stats[key]
            s["days_appeared"] += 1
            s["max_days_open"] = max(s["max_days_open"], item.get("days_open", 1))
            s["max_occurrence"] = max(s["max_occurrence"], item.get("occurrence", 1))

    top_offenders = sorted(
        [v for v in subject_stats.values() if v["days_appeared"] >= 3],
        key=lambda v: (-v["days_appeared"], -v["max_days_open"]),
    )

    # Category breakdown — count item-days and distinct subjects per category
    cat_item_days = defaultdict(int)
    cat_subjects  = defaultdict(set)
    for date, items in days:
        for item in items:
            cat = item.get("category", "(unknown)")
            subj = _subject_label(item)
            cat_item_days[cat] += 1
            cat_subjects[cat].add(subj)
    category_breakdown = sorted(
        [
            {"category": cat, "item_days": cat_item_days[cat],
             "drivers_affected": len(cat_subjects[cat])}
            for cat in cat_item_days
        ],
        key=lambda r: -r["item_days"],
    )

    # Chronic items — days_open >= 5 that still appear yesterday
    chronic_items = sorted(
        [i for i in yesterday_items if i.get("days_open", 1) >= 5],
        key=lambda i: -i.get("days_open", 1),
    )

    # Resolution rate — items in oldest file not in yesterday's file
    oldest_keys    = {_accountability_key(i) for i in oldest_items}
    yesterday_keys = {_accountability_key(i) for i in yesterday_items}
    resolved_count = len(oldest_keys - yesterday_keys)
    total_old      = len(oldest_keys)

    # Escalation — occurrence >= 3 OR severity == critical in yesterday
    escalation_items = [
        i for i in yesterday_items
        if i.get("occurrence", 1) >= 3 or i.get("severity") == "critical"
    ]

    total_item_days = sum(len(items) for _, items in days)
    unique_subjects = len({_subject_label(i) for _, items in days for i in items})

    return {
        "yesterday_date": yesterday_date,
        "oldest_date": oldest_date,
        "yesterday_items": yesterday_items,
        "oldest_items": oldest_items,
        "top_offenders": top_offenders,
        "category_breakdown": category_breakdown,
        "chronic_items": chronic_items,
        "resolved_count": resolved_count,
        "total_old": total_old,
        "escalation_items": escalation_items,
        "total_item_days": total_item_days,
        "unique_subjects": unique_subjects,
    }


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

_CSS = f"""
body {{
    font-family: Arial, Helvetica, sans-serif;
    font-size: 14px;
    color: {INK};
    background: #f5f5f5;
    margin: 0; padding: 0;
}}
.wrap {{
    max-width: 750px;
    margin: 24px auto;
    background: #fff;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,.12);
}}
.header {{
    background: {XFREIGHT_RED};
    color: #fff;
    padding: 22px 28px 18px;
}}
.header h1 {{
    margin: 0 0 4px;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: .5px;
}}
.header .sub {{
    font-size: 13px;
    opacity: .88;
}}
.body {{
    padding: 24px 28px;
}}
.summary {{
    background: #fde8ea;
    border-left: 4px solid {XFREIGHT_RED};
    padding: 10px 14px;
    margin-bottom: 22px;
    font-weight: 600;
    font-size: 14px;
    color: {INK};
}}
h2 {{
    font-size: 15px;
    font-weight: 700;
    color: {XFREIGHT_RED};
    border-bottom: 2px solid {XFREIGHT_RED};
    padding-bottom: 4px;
    margin: 24px 0 12px;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}}
th {{
    background: {INK};
    color: #fff;
    text-align: left;
    padding: 8px 10px;
    font-weight: 600;
}}
td {{
    padding: 7px 10px;
    border-bottom: 1px solid #e8e8e8;
    vertical-align: top;
}}
tr:last-child td {{ border-bottom: none; }}
tr:nth-child(even) td {{ background: #fafafa; }}
.flag-red {{ color: {XFREIGHT_RED}; font-weight: 700; }}
.resolution-good  {{ color: #0f6b3d; font-weight: 700; }}
.resolution-warn  {{ color: #b58a00; font-weight: 700; }}
.resolution-bad   {{ color: {XFREIGHT_RED}; font-weight: 700; }}
.esc-box {{
    background: #fde8ea;
    border: 1px solid {XFREIGHT_RED};
    border-radius: 4px;
    padding: 12px 14px;
    font-size: 13px;
}}
.esc-row {{
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px solid #f5c6cb;
}}
.esc-row:last-child {{ border-bottom: none; margin-bottom: 0; }}
.footer {{
    text-align: center;
    padding: 16px;
    font-size: 12px;
    color: #888;
    border-top: 1px solid #e8e8e8;
}}
.none-msg {{ color: #555; font-style: italic; margin: 6px 0; }}
"""


def _resolution_class(resolved, total):
    if total == 0:
        return "resolution-warn"
    rate = resolved / total
    if rate >= 0.7:
        return "resolution-good"
    if rate >= 0.4:
        return "resolution-warn"
    return "resolution-bad"


def _build_email(analysis, monday_date):
    ydate = analysis["yesterday_date"]
    odate = analysis["oldest_date"]
    date_range = f"{odate.strftime('%b %-d')} – {ydate.strftime('%b %-d, %Y')}"

    top       = analysis["top_offenders"]
    cat_bd    = analysis["category_breakdown"]
    chronic   = analysis["chronic_items"]
    resolved  = analysis["resolved_count"]
    total_old = analysis["total_old"]
    esc       = analysis["escalation_items"]
    total_item_days = analysis["total_item_days"]
    unique_subj     = analysis["unique_subjects"]

    res_class = _resolution_class(resolved, total_old)
    if total_old:
        res_text = f"{resolved} of {total_old} items from {odate.strftime('%b %-d')} resolved this week"
    else:
        res_text = "No data from oldest day to compare"

    # Top offenders table
    if top:
        top_rows = "".join(
            "<tr>"
            f"<td>{v['name']}</td>"
            f"<td>{v['category']}</td>"
            f"<td style='text-align:center'>{v['days_appeared']}</td>"
            f"<td style='text-align:center'>{v['max_days_open']}</td>"
            f"<td style='text-align:center'>{v['max_occurrence']}</td>"
            f"<td style='text-align:center'>"
            + ('<span class="flag-red">\U0001f534 Written Warning</span>'
               if v["max_occurrence"] >= 3 else "—")
            + "</td></tr>"
            for v in top
        )
        top_section = (
            "<h2>Top Offenders — 3+ Days This Week</h2>"
            "<table>"
            "<tr><th>Name</th><th>Category</th><th>Days</th>"
            "<th>Max Days Open</th><th>Occurrences (30d)</th><th>Status</th></tr>"
            + top_rows
            + "</table>"
        )
    else:
        top_section = (
            "<h2>Top Offenders — 3+ Days This Week</h2>"
            "<p class='none-msg'>No driver or unit appeared in 3+ days this week.</p>"
        )

    # Category breakdown table
    cat_rows = "".join(
        "<tr>"
        f"<td>{r['category']}</td>"
        f"<td style='text-align:center'>{r['item_days']}</td>"
        f"<td style='text-align:center'>{r['drivers_affected']}</td>"
        "</tr>"
        for r in cat_bd
    )
    cat_section = (
        "<h2>Category Breakdown</h2>"
        "<table>"
        "<tr><th>Category</th><th>Item-Days</th><th>Drivers / Units Affected</th></tr>"
        + (cat_rows if cat_rows else "<tr><td colspan='3' class='none-msg'>No data this week.</td></tr>")
        + "</table>"
    )

    # Chronic items
    if chronic:
        chronic_rows = "".join(
            "<tr>"
            f"<td>{_subject_label(i)}</td>"
            f"<td>{i.get('category','')}</td>"
            f"<td style='text-align:center'>{i.get('days_open',1)}</td>"
            f"<td>{i.get('detail','')}</td>"
            "</tr>"
            for i in chronic
        )
        chronic_section = (
            "<h2>Chronic Items — Open 5+ Days</h2>"
            "<table>"
            "<tr><th>Name</th><th>Category</th><th>Days Open</th><th>Detail</th></tr>"
            + chronic_rows
            + "</table>"
        )
    else:
        chronic_section = (
            "<h2>Chronic Items — Open 5+ Days</h2>"
            "<p class='none-msg'>No items open 5+ days — good.</p>"
        )

    resolution_section = (
        "<h2>Resolution Rate</h2>"
        f"<p class='{res_class}'>{res_text}</p>"
    )

    # Escalation
    if esc:
        esc_rows = ""
        for i in esc:
            reasons = []
            if i.get("occurrence", 1) >= 3:
                reasons.append(f"\U0001f534 occurrence #{i.get('occurrence',1)} in 30d")
            if i.get("severity") == "critical":
                reasons.append("critical severity")
            reason_str = " | ".join(reasons)
            esc_rows += (
                f"<div class='esc-row'>"
                f"<strong>{_subject_label(i)}</strong> — {i.get('category','')} "
                f"({reason_str})"
                f"<br><span style='color:#555'>{i.get('prompt','')}</span>"
                f"</div>"
            )
        esc_section = (
            "<h2>Escalation Needed — JB Attention Required</h2>"
            f"<div class='esc-box'>{esc_rows}</div>"
        )
    else:
        esc_section = (
            "<h2>Escalation Needed</h2>"
            "<p class='none-msg'>No items requiring escalation this week.</p>"
        )

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_CSS}</style></head><body>"
        "<div class='wrap'>"
        "<div class='header'>"
        "<h1>XFreight Weekly Safety Pattern Report</h1>"
        f"<div class='sub'>{date_range}</div>"
        "</div>"
        "<div class='body'>"
        "<div class='summary'>"
        f"{total_item_days} total item-days across {unique_subj} unique drivers/units this week"
        "</div>"
        + top_section
        + cat_section
        + chronic_section
        + resolution_section
        + esc_section
        + "</div>"
        "<div class='footer'>Review the daily Safety &amp; Compliance brief for full details.</div>"
        "</div></body></html>"
    )


def _build_no_data_email():
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>body{{font-family:Arial,sans-serif;font-size:14px;color:{INK};background:#f5f5f5;}}"
        f".wrap{{max-width:600px;margin:40px auto;background:#fff;border-radius:6px;padding:28px;"
        f"box-shadow:0 2px 8px rgba(0,0,0,.12);}}"
        f"h1{{color:{XFREIGHT_RED};font-size:20px;}}"
        "</style></head><body>"
        "<div class='wrap'>"
        "<h1>XFreight Weekly Safety Pattern Report</h1>"
        "<p>No accountability data files were found for the past 7 days. "
        "The report could not be generated.</p>"
        "<p style='color:#888;font-size:12px;'>This message was sent automatically by the weekly accountability report job.</p>"
        "</div></body></html>"
    )


# ---------------------------------------------------------------------------
# Teams card builder
# ---------------------------------------------------------------------------

def _build_teams_card(analysis, date_range):
    top3     = analysis["top_offenders"][:3]
    resolved = analysis["resolved_count"]
    total_old = analysis["total_old"]
    esc_count = len(analysis["escalation_items"])

    top3_text = "\n".join(
        f"• {v['name']} — {v['category']} ({v['days_appeared']}d)"
        for v in top3
    ) or "No repeat offenders this week."

    res_text = f"{resolved}/{total_old}" if total_old else "n/a"

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "Container",
                "style": "emphasis",
                "bleed": True,
                "items": [
                    {
                        "type": "TextBlock",
                        "text": f"\U0001f4ca Weekly Safety Pattern — {date_range}",
                        "weight": "Bolder",
                        "size": "Medium",
                        "color": "Light",
                        "wrap": True,
                    }
                ],
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Total item-days",          "value": str(analysis["total_item_days"])},
                    {"title": "Unique drivers/units",     "value": str(analysis["unique_subjects"])},
                    {"title": "Resolved this week",       "value": res_text},
                    {"title": "Items needing escalation", "value": str(esc_count)},
                ],
                "spacing": "Medium",
            },
            {
                "type": "TextBlock",
                "text": "**Top 3 Repeat Offenders**",
                "weight": "Bolder",
                "spacing": "Medium",
            },
            {
                "type": "TextBlock",
                "text": top3_text,
                "wrap": True,
                "spacing": "Small",
            },
        ],
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


def _post_teams(webhook, payload):
    if not webhook:
        log.info("TEAMS_SAFETY_WEBHOOK not set — skipping Teams post.")
        return
    try:
        resp = requests.post(webhook, json=payload, timeout=30)
        log.info("Teams card posted: HTTP %s", resp.status_code)
        if resp.status_code not in range(200, 300):
            log.warning("Teams response body: %s", resp.text[:300])
    except Exception as exc:
        log.warning("Teams post failed: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    tenant = os.environ.get("AZURE_TENANT_ID", "")
    cid    = os.environ.get("AZURE_CLIENT_ID", "")
    secret = os.environ.get("AZURE_CLIENT_SECRET", "")
    upn    = os.environ.get("ONEDRIVE_USER_UPN", "")

    if not all([tenant, cid, secret, upn]):
        log.error(
            "Missing Azure credentials — need AZURE_TENANT_ID, AZURE_CLIENT_ID, "
            "AZURE_CLIENT_SECRET, ONEDRIVE_USER_UPN"
        )
        return 1

    to_raw  = os.environ.get("SAFETY_TO_EMAILS", "audra@xfreight.net")
    cc_raw  = os.environ.get("SAFETY_CC_EMAILS", "jb@xfreight.net,jeff@xfreight.net")
    webhook = os.environ.get("TEAMS_SAFETY_WEBHOOK", "").strip()

    to_emails = [e.strip() for e in to_raw.split(",") if e.strip()]
    cc_emails = [e.strip() for e in cc_raw.split(",") if e.strip()] if cc_raw else []

    tok = get_token(tenant, cid, secret)

    try:
        from zoneinfo import ZoneInfo
        today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:
        today = datetime.date.today()

    monday_date = today - datetime.timedelta(days=today.weekday())

    log.info("Loading 7-day accountability data (today = %s)", today.isoformat())
    days = _load_week(tok, upn, today)
    log.info("Loaded %d day(s) of data", len(days))

    subject = f"XFreight Weekly Safety Pattern — Week of {monday_date.strftime('%B %-d, %Y')}"

    if not days:
        log.warning("No accountability data found for the past 7 days — sending no-data notice.")
        html = _build_no_data_email()
        send_email(tok, upn, to_emails, subject, html, cc_emails=cc_emails or None)
        return 0

    analysis = _analyse(days)

    ydate = analysis["yesterday_date"]
    odate = analysis["oldest_date"]
    date_range = f"{odate.strftime('%b %-d')} – {ydate.strftime('%b %-d, %Y')}"

    log.info(
        "Analysis: %d total item-days, %d unique subjects, %d top offenders, "
        "%d chronic, %d/%d resolved, %d escalations",
        analysis["total_item_days"], analysis["unique_subjects"],
        len(analysis["top_offenders"]), len(analysis["chronic_items"]),
        analysis["resolved_count"], analysis["total_old"],
        len(analysis["escalation_items"]),
    )

    html = _build_email(analysis, monday_date)
    send_email(tok, upn, to_emails, subject, html, cc_emails=cc_emails or None)
    log.info("Weekly accountability email sent to %s", to_emails)

    teams_payload = _build_teams_card(analysis, date_range)
    _post_teams(webhook, teams_payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
