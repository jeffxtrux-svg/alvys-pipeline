"""Render three single-page style-comparison PDFs of the XFreight Executive Brief.

Each PDF shows the same data laid out in a different aesthetic:

  1. Executive consulting brief   — Navy + black/grey, serif headlines, hero numbers
  2. Modern financial report      — Single column, generous margins, variance-only color
  3. Polished operational dashboard — Multi-tile grid but unified card system

The point is to pick a direction. Once picked, that style gets applied to
the full daily brief.

Run locally:
    python -m src.style_samples
"""
from __future__ import annotations

import base64
import datetime
import logging
import os
import sys

import requests
from dotenv import load_dotenv

log = logging.getLogger("style_samples")

GRAPH = "https://graph.microsoft.com/v1.0"


# ----------------------------------------------------------------------
# Sample data — representative of what the daily brief carries.
# Hard-coded so the style samples can be built without any OneDrive read.
# ----------------------------------------------------------------------
SAMPLE = {
    "date": "Thursday, June 4, 2026",
    "xtrux": {
        "loads": 36,
        "revenue": 69036,
        "rpm": 2.89,
        "dh_pct": 5.5,
        "margin": 28.4,
        "miles": 23917,
    },
    "xlinx": {
        "loads": 142,
        "revenue": 198450,
        "margin_pct": 12.1,
    },
    "ar": {
        "total": 487320,
        "past_due_31": 142800,
        "past_due_91": 38900,
    },
    "rpm_goal": {
        "cost": 2.63,
        "goal": 2.76,
        "actual": 2.76,
    },
    "safety": {
        "events_24h": 4,
        "hos_24h": 1,
        "dvir_open": 3,
        "fleet_score": 98,
    },
}


# ----------------------------------------------------------------------
# Style 1 — Executive consulting brief
# Navy + grey, serif headlines, hero numbers, lots of whitespace.
# ----------------------------------------------------------------------
def render_executive(d: dict) -> str:
    s = d["xtrux"]
    x = d["xlinx"]
    a = d["ar"]
    r = d["rpm_goal"]
    css = """
    <style>
      @page { size: letter; margin: 0.75in; }
      body {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #111;
        font-size: 11pt;
        line-height: 1.5;
        -webkit-print-color-adjust: exact;
      }
      h1 {
        font-family: Georgia, 'Times New Roman', serif;
        font-weight: 400;
        font-size: 26pt;
        color: #0b2545;
        margin: 0 0 4px;
        letter-spacing: -0.5px;
      }
      .subhead {
        font-size: 10pt;
        color: #777;
        margin-bottom: 28px;
        border-bottom: 1px solid #d1d5db;
        padding-bottom: 14px;
      }
      h2 {
        font-family: Georgia, serif;
        font-weight: 400;
        font-size: 14pt;
        color: #0b2545;
        margin: 28px 0 12px;
        letter-spacing: -0.2px;
      }
      .row { display: flex; gap: 36px; margin: 18px 0; }
      .stat { flex: 1; }
      .stat .label {
        font-size: 9pt;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        color: #6b7280;
        font-weight: 600;
        margin-bottom: 6px;
      }
      .stat .value {
        font-family: Georgia, serif;
        font-size: 30pt;
        color: #0b2545;
        font-weight: 400;
        letter-spacing: -1px;
        line-height: 1;
      }
      .stat .context {
        font-size: 9.5pt;
        color: #6b7280;
        margin-top: 6px;
      }
      .narrative {
        background: #f7f8fa;
        border-left: 3px solid #0b2545;
        padding: 14px 18px;
        margin: 20px 0 0;
        font-size: 10.5pt;
        line-height: 1.6;
      }
      .narrative .key { color: #0b2545; font-weight: 600; }
    </style>
    """
    body = f"""
    <h1>XFreight Executive Brief</h1>
    <div class='subhead'>{d['date']}</div>

    <div class='narrative'>
      <span class='key'>The bottom line.</span>
      X-Trux is running ${s['rpm']:.2f}/mi against a ${r['goal']:.2f}/mi target — a
      ${r['goal']-s['rpm']:.2f}/mi gap on {s['miles']:,} miles month-to-date.
      Dead-head sits at {s['dh_pct']:.1f}%. AR over 31 days stands at
      ${a['past_due_31']:,} ({(a['past_due_31']/a['total']*100):.0f}% of total).
    </div>

    <h2>X-Trux · month-to-date</h2>
    <div class='row'>
      <div class='stat'>
        <div class='label'>Revenue</div>
        <div class='value'>${s['revenue']/1000:.0f}K</div>
        <div class='context'>across {s['loads']} loads</div>
      </div>
      <div class='stat'>
        <div class='label'>Revenue per mile</div>
        <div class='value'>${s['rpm']:.2f}</div>
        <div class='context'>target ${r['goal']:.2f} · cost ${r['cost']:.2f}</div>
      </div>
      <div class='stat'>
        <div class='label'>Dead-head</div>
        <div class='value'>{s['dh_pct']:.1f}%</div>
        <div class='context'>{s['miles']:,} dispatch miles</div>
      </div>
    </div>

    <h2>X-Linx · month-to-date</h2>
    <div class='row'>
      <div class='stat'>
        <div class='label'>Revenue</div>
        <div class='value'>${x['revenue']/1000:.0f}K</div>
        <div class='context'>{x['loads']} loads brokered</div>
      </div>
      <div class='stat'>
        <div class='label'>Gross margin</div>
        <div class='value'>{x['margin_pct']:.1f}%</div>
        <div class='context'>brokerage spread</div>
      </div>
      <div class='stat'></div>
    </div>

    <h2>Accounts receivable</h2>
    <div class='row'>
      <div class='stat'>
        <div class='label'>Total AR</div>
        <div class='value'>${a['total']/1000:.0f}K</div>
        <div class='context'>open receivables</div>
      </div>
      <div class='stat'>
        <div class='label'>Past due 31+</div>
        <div class='value'>${a['past_due_31']/1000:.0f}K</div>
        <div class='context'>{(a['past_due_31']/a['total']*100):.0f}% of total</div>
      </div>
      <div class='stat'>
        <div class='label'>Past due 91+</div>
        <div class='value'>${a['past_due_91']/1000:.0f}K</div>
        <div class='context'>escalate to collections</div>
      </div>
    </div>
    """
    return f"<!doctype html><html><head>{css}</head><body>{body}</body></html>"


# ----------------------------------------------------------------------
# Style 2 — Modern financial report
# Pure white, single column, generous margins, variance-only color.
# ----------------------------------------------------------------------
def render_financial(d: dict) -> str:
    s = d["xtrux"]
    x = d["xlinx"]
    a = d["ar"]
    r = d["rpm_goal"]
    css = """
    <style>
      @page { size: letter; margin: 0.9in; }
      body {
        font-family: 'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #0a0a0a;
        font-size: 10.5pt;
        line-height: 1.55;
        -webkit-print-color-adjust: exact;
      }
      .header { margin-bottom: 32px; }
      .header .label {
        font-size: 9pt;
        text-transform: uppercase;
        letter-spacing: 2px;
        color: #737373;
        font-weight: 600;
      }
      .header .title {
        font-size: 22pt;
        font-weight: 800;
        margin: 6px 0 4px;
        letter-spacing: -0.5px;
      }
      .header .date { font-size: 10pt; color: #737373; }
      h2 {
        font-size: 11pt;
        font-weight: 700;
        margin: 36px 0 12px;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: #0a0a0a;
        border-bottom: 2px solid #0a0a0a;
        padding-bottom: 6px;
      }
      .summary {
        font-size: 11pt;
        line-height: 1.65;
        margin-bottom: 32px;
        padding-bottom: 20px;
        border-bottom: 1px solid #e5e5e5;
      }
      table.kpi {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 0;
      }
      table.kpi td {
        padding: 14px 0;
        border-bottom: 1px solid #e5e5e5;
        font-size: 10.5pt;
      }
      table.kpi td.metric {
        font-weight: 500;
        color: #0a0a0a;
        width: 50%;
      }
      table.kpi td.value {
        text-align: right;
        font-weight: 700;
        font-size: 13pt;
        letter-spacing: -0.3px;
      }
      table.kpi td.context {
        text-align: right;
        font-size: 9.5pt;
        color: #737373;
        width: 30%;
      }
      .positive { color: #15803d; }
      .negative { color: #b91c1c; }
    </style>
    """
    gap = r['goal'] - s['rpm']
    body = f"""
    <div class='header'>
      <div class='label'>XFreight Holdings</div>
      <div class='title'>Daily Executive Brief</div>
      <div class='date'>{d['date']}</div>
    </div>

    <div class='summary'>
      X-Trux revenue is <b>${s['revenue']:,}</b> month-to-date across {s['loads']} loads, running
      ${s['rpm']:.2f}/mi against the ${r['goal']:.2f}/mi target. Dead-head sits at {s['dh_pct']:.1f}%.
      X-Linx contributed <b>${x['revenue']:,}</b> at {x['margin_pct']:.1f}% gross margin.
      Total receivables are <b>${a['total']:,}</b>, with <b>${a['past_due_31']:,}</b> past 31 days
      ({(a['past_due_31']/a['total']*100):.0f}% of the book).
    </div>

    <h2>X-Trux — Asset Trucking</h2>
    <table class='kpi'>
      <tr><td class='metric'>Revenue (MTD)</td><td class='context'>{s['loads']} loads</td><td class='value'>${s['revenue']:,}</td></tr>
      <tr><td class='metric'>Revenue per mile</td><td class='context'>target ${r['goal']:.2f}</td><td class='value'>${s['rpm']:.2f}</td></tr>
      <tr><td class='metric'>Gap to goal</td><td class='context'>{s['miles']:,} mi</td><td class='value negative'>−${gap:.2f}</td></tr>
      <tr><td class='metric'>Dead-head</td><td class='context'>target ≤ 5%</td><td class='value negative'>{s['dh_pct']:.1f}%</td></tr>
      <tr><td class='metric'>Contribution margin</td><td class='context'></td><td class='value positive'>{s['margin']:.1f}%</td></tr>
    </table>

    <h2>X-Linx — Brokerage</h2>
    <table class='kpi'>
      <tr><td class='metric'>Revenue (MTD)</td><td class='context'>{x['loads']} loads</td><td class='value'>${x['revenue']:,}</td></tr>
      <tr><td class='metric'>Gross margin</td><td class='context'></td><td class='value positive'>{x['margin_pct']:.1f}%</td></tr>
    </table>

    <h2>Accounts Receivable</h2>
    <table class='kpi'>
      <tr><td class='metric'>Total open AR</td><td class='context'>QuickBooks</td><td class='value'>${a['total']:,}</td></tr>
      <tr><td class='metric'>Past due 31+ days</td><td class='context'>{(a['past_due_31']/a['total']*100):.0f}% of book</td><td class='value negative'>${a['past_due_31']:,}</td></tr>
      <tr><td class='metric'>Past due 91+ days</td><td class='context'>escalate to collections</td><td class='value negative'>${a['past_due_91']:,}</td></tr>
    </table>
    """
    return f"<!doctype html><html><head>{css}</head><body>{body}</body></html>"


# ----------------------------------------------------------------------
# Style 3 — Polished operational dashboard
# Multi-tile, but a unified card system: same radius / border / padding /
# shadow on every tile, calmer palette, consistent rhythm.
# ----------------------------------------------------------------------
def render_dashboard(d: dict) -> str:
    s = d["xtrux"]
    x = d["xlinx"]
    a = d["ar"]
    r = d["rpm_goal"]
    sa = d["safety"]
    css = """
    <style>
      @page { size: letter; margin: 0.5in; }
      body {
        font-family: 'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        color: #0f172a;
        font-size: 10.5pt;
        line-height: 1.5;
        background: #f8fafc;
        margin: 0;
        -webkit-print-color-adjust: exact;
      }
      .page-header {
        background: #0f172a;
        color: #fff;
        padding: 18px 24px;
        margin-bottom: 20px;
        border-radius: 10px;
      }
      .page-header .label {
        font-size: 9pt;
        text-transform: uppercase;
        letter-spacing: 2.5px;
        color: #94a3b8;
        font-weight: 700;
        margin-bottom: 4px;
      }
      .page-header .title {
        font-size: 18pt;
        font-weight: 700;
        letter-spacing: -0.3px;
      }
      .page-header .date {
        font-size: 10pt;
        color: #cbd5e1;
        margin-top: 2px;
      }
      .section {
        font-size: 9.5pt;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: #475569;
        font-weight: 700;
        margin: 24px 4px 10px;
      }
      .grid { display: flex; gap: 12px; margin-bottom: 4px; }
      .card {
        flex: 1;
        background: #fff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
      }
      .card .label {
        font-size: 9pt;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        color: #64748b;
        font-weight: 600;
        margin-bottom: 6px;
      }
      .card .value {
        font-size: 22pt;
        font-weight: 800;
        color: #0f172a;
        letter-spacing: -0.6px;
        line-height: 1.1;
        margin-bottom: 4px;
      }
      .card .context {
        font-size: 9pt;
        color: #64748b;
      }
      .card.negative .value { color: #b91c1c; }
      .card.positive .value { color: #15803d; }
    </style>
    """
    gap = r['goal'] - s['rpm']
    body = f"""
    <div class='page-header'>
      <div class='label'>XFreight Holdings · Executive Brief · Page 1 of 12</div>
      <div class='title'>Morning Executive Brief</div>
      <div class='date'>{d['date']}</div>
    </div>

    <div class='section'>X-Trux Overview · MTD</div>
    <div class='grid'>
      <div class='card'>
        <div class='label'>Loads</div>
        <div class='value'>{s['loads']}</div>
        <div class='context'>dispatched + delivered</div>
      </div>
      <div class='card'>
        <div class='label'>Revenue</div>
        <div class='value'>${s['revenue']/1000:.0f}K</div>
        <div class='context'>${s['revenue']:,} total</div>
      </div>
      <div class='card'>
        <div class='label'>Rev / mile</div>
        <div class='value'>${s['rpm']:.2f}</div>
        <div class='context'>target ${r['goal']:.2f}</div>
      </div>
      <div class='card negative'>
        <div class='label'>Dead-head</div>
        <div class='value'>{s['dh_pct']:.1f}%</div>
        <div class='context'>{s['miles']:,} dispatch mi</div>
      </div>
    </div>

    <div class='section'>X-Trux Rate-per-Mile Goal</div>
    <div class='grid'>
      <div class='card'>
        <div class='label'>Cost / mile</div>
        <div class='value'>${r['cost']:.2f}</div>
        <div class='context'>10d pay + YTD overhead</div>
      </div>
      <div class='card'>
        <div class='label'>Goal rate</div>
        <div class='value'>${r['goal']:.2f}</div>
        <div class='context'>5.0% net · OR 0.95</div>
      </div>
      <div class='card'>
        <div class='label'>Actual / mile</div>
        <div class='value'>${r['actual']:.2f}</div>
        <div class='context'>last 10 days</div>
      </div>
      <div class='card negative'>
        <div class='label'>Gap to goal</div>
        <div class='value'>${gap:.2f}</div>
        <div class='context'>below goal</div>
      </div>
    </div>

    <div class='section'>X-Linx Overview · MTD</div>
    <div class='grid'>
      <div class='card'>
        <div class='label'>Loads</div>
        <div class='value'>{x['loads']}</div>
        <div class='context'>brokered</div>
      </div>
      <div class='card'>
        <div class='label'>Revenue</div>
        <div class='value'>${x['revenue']/1000:.0f}K</div>
        <div class='context'>${x['revenue']:,} total</div>
      </div>
      <div class='card positive'>
        <div class='label'>Gross margin</div>
        <div class='value'>{x['margin_pct']:.1f}%</div>
        <div class='context'>brokerage spread</div>
      </div>
      <div class='card'></div>
    </div>

    <div class='section'>Accounts Receivable</div>
    <div class='grid'>
      <div class='card'>
        <div class='label'>Total AR</div>
        <div class='value'>${a['total']/1000:.0f}K</div>
        <div class='context'>open receivables</div>
      </div>
      <div class='card negative'>
        <div class='label'>Past due 31+</div>
        <div class='value'>${a['past_due_31']/1000:.0f}K</div>
        <div class='context'>{(a['past_due_31']/a['total']*100):.0f}% of book</div>
      </div>
      <div class='card negative'>
        <div class='label'>Past due 91+</div>
        <div class='value'>${a['past_due_91']/1000:.0f}K</div>
        <div class='context'>collections</div>
      </div>
      <div class='card'>
        <div class='label'>Fleet safety</div>
        <div class='value'>{sa['fleet_score']}</div>
        <div class='context'>{sa['events_24h']} events 24h</div>
      </div>
    </div>
    """
    return f"<!doctype html><html><head>{css}</head><body>{body}</body></html>"


# ----------------------------------------------------------------------
# PDF render + email
# ----------------------------------------------------------------------
def _render_pdf(html: str) -> bytes:
    from weasyprint import HTML  # type: ignore
    for _lg in ("weasyprint", "fontTools", "fontTools.subset",
                "fontTools.ttLib", "fontTools.ttLib.ttFont"):
        _lo = logging.getLogger(_lg)
        _lo.setLevel(logging.ERROR)
        _lo.propagate = False
    return HTML(string=html).write_pdf()


def _send(token: str, from_upn: str, to_emails: list[str], subject: str,
          html: str, attachments: list[dict]) -> None:
    url = f"{GRAPH}/users/{from_upn}/sendMail"
    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to_emails],
        "attachments": [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": a["name"],
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(a["content"]).decode("ascii"),
            }
            for a in attachments
        ],
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": message},
        timeout=60,
    )
    resp.raise_for_status()
    log.info("Sample email sent to %s with %d attachment(s)",
             ", ".join(to_emails), len(attachments))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    upn = os.environ.get("ONEDRIVE_USER_UPN")
    to_raw = os.environ.get("SCORECARD_TO_EMAILS", upn or "")
    if not all([tenant, client, secret, upn]):
        sys.exit("ERROR: AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET + ONEDRIVE_USER_UPN required")
    to_emails = [e.strip() for e in to_raw.split(",") if e.strip()]

    from src.onedrive_upload import get_token
    token = get_token(tenant, client, secret)

    samples = [
        ("Executive consulting brief", render_executive, "01_executive_consulting.pdf"),
        ("Modern financial report",    render_financial, "02_modern_financial.pdf"),
        ("Polished dashboard",         render_dashboard, "03_polished_dashboard.pdf"),
    ]
    attachments = []
    descriptions = []
    for title, fn, fname in samples:
        log.info("Rendering: %s …", title)
        html = fn(SAMPLE)
        pdf = _render_pdf(html)
        attachments.append({"name": fname, "content": pdf})
        descriptions.append(f"<li><b>{fname}</b> — {title}</li>")
        log.info("  %s → %.1f KB", fname, len(pdf) / 1024)

    body = (
        "<p>Three style samples of the executive brief — same data, different aesthetics. "
        "Open each PDF, pick the one you want me to apply to the full daily brief.</p>"
        "<ol>" + "".join(descriptions) + "</ol>"
        "<p>Reply with the filename you want (e.g. <code>01_executive_consulting</code>) and "
        "I'll restyle the full brief in that direction.</p>"
    )
    _send(token, upn, to_emails,
          f"XFreight brief — style samples ({datetime.datetime.now():%b %d})",
          body, attachments)
    return 0


if __name__ == "__main__":
    sys.exit(main())
