"""Weekly Risk & Decisions report — a SECONDARY email, separate from the daily
executive brief.

Renders the knowledge base's two decision-support pages —
`Karpathy-Wiki/wiki/risk-register.md` and `decision-journal.md` — into a clean,
XFreight-branded HTML email and sends it via Microsoft Graph (reusing the daily
brief's auth + send path). Includes "Discuss with Claude" links that open a new
chat seeded with a starter question per topic.

This is deliberately decoupled from `scorecard_email.py`: the daily brief is
untouched. Run weekly (Monday 7am CT) from `.github/workflows/decision_report.yml`,
or on demand via workflow_dispatch / editing that workflow file.

    python -m src.decision_report          # build + send
    python -m src.decision_report --dry     # build + write /tmp preview, no send
"""
from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from src.onedrive_upload import get_token
# Reuse the brief's Graph send + brand palette so the two reports look like
# siblings and there's one auth path to maintain.
from src.scorecard_email import (send_email, XFREIGHT_RED, INK, MUTE, LINE,
                                  GOOD, GOODBG, BAD, BADBG, FONT, FONT_SERIF)

log = logging.getLogger("decision_report")

WIKI_DIR = os.environ.get("DECISION_REPORT_WIKI_DIR", "Karpathy-Wiki/wiki")

# XFreight wordmark (same SVG the daily brief uses).
_XF_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 220 38' width='150' height='26' "
    "role='img' aria-label='XFreight'><rect width='220' height='38' rx='2' fill='#c41e2a'/>"
    "<g fill='#fff'><rect x='8' y='6' width='38' height='2.4'/><rect x='10' y='10' width='34' height='2.4'/>"
    "<rect x='6' y='14' width='42' height='2.4'/><rect x='12' y='18' width='30' height='2.4'/>"
    "<rect x='8' y='22' width='38' height='2.4'/><rect x='10' y='26' width='34' height='2.4'/>"
    "<rect x='6' y='30' width='42' height='2.4'/></g><text x='56' y='27' "
    "font-family='Helvetica,Arial,sans-serif' font-weight='900' font-style='italic' "
    "font-size='22' letter-spacing='-0.5' fill='#fff'>XFREIGHT</text></svg>"
)

# Starter prompts for the "Discuss with Claude" buttons. Each opens a new chat
# pre-seeded with the question (and the text is shown for copy-paste in case the
# prefill doesn't carry through).
CLAUDE_PROMPTS = [
    ("Review my top risks",
     "Walk me through XFreight's current top risks from the risk register and what I should do about each this week."),
    ("Grade open decisions",
     "Help me grade the open decisions in XFreight's decision journal — which assumptions should I re-check, and which outcomes can we measure now?"),
    ("Quantify customer concentration",
     "Help me quantify XFreight's customer concentration — what share of X-Trux + X-Linx revenue each top customer represents, and at what point it becomes a real risk."),
]


def _claude_link(prompt: str) -> str:
    """A claude.ai 'new chat' URL seeded with prompt. Degrades gracefully — if the
    query param isn't honored, the link still opens a fresh chat."""
    from urllib.parse import quote
    return f"https://claude.ai/new?q={quote(prompt)}"


# ----------------------------------------------------------------------
# Minimal markdown -> inline-styled HTML (the subset our wiki pages use).
# Inline styles + table layout keep it email-client safe (Outlook/Gmail).
# ----------------------------------------------------------------------
def _inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                  rf"<a href='\2' style='color:{XFREIGHT_RED};'>\1</a>", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)          # KB-internal links -> plain
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", rf"<em style='color:{MUTE};'>\1</em>", text)
    text = re.sub(r"`([^`]+)`",
                  r"<code style='background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:12px;'>\1</code>", text)
    return text


def _split_row(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _render_table(rows: list[str]) -> str:
    header = _split_row(rows[0])
    th = "".join(
        f"<th style='text-align:left;padding:7px 10px;font-size:11px;text-transform:uppercase;"
        f"letter-spacing:.4px;color:{MUTE};border-bottom:2px solid {LINE};'>{_inline(h)}</th>"
        for h in header)
    trs = []
    for k, r in enumerate(rows[2:]):           # skip header + |---| separator
        bg = "#f8fafc" if k % 2 == 0 else "#fff"
        tds = "".join(
            f"<td style='padding:7px 10px;font-size:13px;border-bottom:1px solid {LINE};"
            f"vertical-align:top;'>{_inline(c)}</td>" for c in _split_row(r))
        trs.append(f"<tr style='background:{bg};'>{tds}</tr>")
    return (f"<table width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;"
            f"margin:10px 0 16px;'><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>")


_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _md_to_html(md: str) -> str:
    lines = md.split("\n")
    if lines and lines[0].strip() == "---":                 # strip YAML frontmatter
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            lines = lines[end + 1:]
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s.startswith("|") and i + 1 < n and _SEP_RE.match(lines[i + 1]) and "-" in lines[i + 1]:
            tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            out.append(_render_table(tbl))
            continue
        if s == "---":
            out.append(f"<hr style='border:none;border-top:1px solid {LINE};margin:20px 0;'>")
            i += 1
            continue
        if s.startswith("### "):
            out.append(f"<h3 style='{FONT_SERIF}font-size:15px;font-weight:600;color:{INK};margin:16px 0 4px;'>{_inline(s[4:])}</h3>")
            i += 1
            continue
        if s.startswith("## "):
            out.append(f"<h2 style='{FONT_SERIF}font-size:18px;font-weight:400;color:{INK};margin:22px 0 6px;border-bottom:1px solid {LINE};padding-bottom:4px;'>{_inline(s[3:])}</h2>")
            i += 1
            continue
        if s.startswith("# "):
            out.append(f"<h1 style='{FONT_SERIF}font-size:21px;font-weight:400;color:{INK};margin:6px 0 8px;'>{_inline(s[2:])}</h1>")
            i += 1
            continue
        if s.startswith(">"):
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f"<div style='background:#f8fafc;border-left:3px solid {LINE};padding:10px 14px;"
                       f"margin:10px 0;font-size:12px;color:{MUTE};'>{_inline(' '.join(quote))}</div>")
            continue
        if s.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(f"<li style='margin:3px 0;'>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            out.append(f"<ul style='font-size:13px;color:{INK};line-height:1.5;margin:8px 0;padding-left:20px;'>{''.join(items)}</ul>")
            continue
        out.append(f"<p style='font-size:13px;color:{INK};line-height:1.6;margin:8px 0;'>{_inline(s)}</p>")
        i += 1
    return "\n".join(out)


# ----------------------------------------------------------------------
# Report shell
# ----------------------------------------------------------------------
def _claude_section() -> str:
    btns = []
    for label, prompt in CLAUDE_PROMPTS:
        href = _claude_link(prompt)
        btns.append(
            f"<a href='{href}' style='display:inline-block;background:{XFREIGHT_RED};color:#fff;"
            f"text-decoration:none;font-size:12px;font-weight:700;padding:8px 14px;border-radius:6px;"
            f"margin:0 8px 8px 0;'>{label} &rarr;</a>")
    return (f"<div style='background:{GOODBG};border:1px solid #cfe6d8;border-radius:8px;padding:14px 16px;margin:14px 0 18px;'>"
            f"<div style='font-size:13px;font-weight:700;color:{INK};margin-bottom:8px;'>Discuss deeper with Claude</div>"
            f"<div>{''.join(btns)}</div>"
            f"<div style='font-size:11px;color:{MUTE};margin-top:4px;'>Each opens a new Claude chat with a starter question you can edit. "
            f"If the prompt doesn't carry over, it's listed at the bottom of this email to copy.</div></div>")


def _prompt_appendix() -> str:
    rows = "".join(
        f"<div style='margin:6px 0;'><span style='font-weight:700;color:{INK};font-size:12px;'>{label}:</span> "
        f"<span style='color:{MUTE};font-size:12px;'>{prompt}</span></div>"
        for label, prompt in CLAUDE_PROMPTS)
    return (f"<div style='margin-top:18px;border-top:1px solid {LINE};padding-top:12px;'>"
            f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:{MUTE};margin-bottom:6px;'>"
            f"Starter prompts (copy into Claude)</div>{rows}</div>")


def build_decision_report(date_str: str, risk_md: str, decision_md: str) -> str:
    header = (
        f"<table width='100%' cellpadding='0' cellspacing='0' style='border-bottom:4px solid {XFREIGHT_RED};padding:6px 0 14px;'>"
        f"<tr><td valign='middle'>{_XF_SVG}"
        f"<div style='{FONT_SERIF}font-style:italic;font-size:16px;color:{INK};margin-top:8px;'>Risk &amp; Decisions Report</div>"
        f"<div style='font-size:12px;color:{MUTE};margin-top:2px;'>Weekly &middot; separate from the daily executive brief</div></td>"
        f"<td align='right' valign='middle' style='font-size:11px;color:{MUTE};'>{date_str}</td></tr></table>")
    risk_html = _md_to_html(risk_md) if risk_md else f"<p style='color:{MUTE};'>Risk register not found.</p>"
    decision_html = _md_to_html(decision_md) if decision_md else f"<p style='color:{MUTE};'>Decision journal not found.</p>"
    return (
        f"<div style=\"max-width:720px;margin:0 auto;padding:8px 18px 24px;{FONT}\">"
        f"{header}"
        f"{_claude_section()}"
        f"{risk_html}"
        f"<div style='height:8px;'></div>"
        f"{decision_html}"
        f"{_prompt_appendix()}"
        f"<div style='margin-top:18px;border-top:1px solid {LINE};padding-top:10px;font-size:11px;color:{MUTE};'>"
        f"Source: Karpathy-Wiki knowledge base (Risk Register + Decision Journal). "
        f"This is a standalone weekly report — the daily executive brief is unchanged.</div>"
        f"</div>")


def _read_wiki(name: str) -> str:
    path = os.path.join(WIKI_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        log.warning("decision_report: could not read %s: %s", path, exc)
        return ""


def _today_central() -> str:
    return datetime.now(ZoneInfo("America/Chicago")).strftime("%A, %B %d, %Y")


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    load_dotenv()

    date_str = _today_central()
    risk_md = _read_wiki("risk-register.md")
    decision_md = _read_wiki("decision-journal.md")
    html = build_decision_report(date_str, risk_md, decision_md)
    subject = f"XFreight Risk & Decisions — {date_str}"

    if "--dry" in sys.argv:
        out = "/tmp/decision_report.html"
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        log.info("Dry run — wrote %s (%d bytes), no email sent.", out, len(html))
        return 0

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    upn = os.environ.get("ONEDRIVE_USER_UPN")
    if not all([tenant, client, secret, upn]):
        sys.exit("ERROR: AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET and ONEDRIVE_USER_UPN are required")
    from_upn = os.environ.get("SCORECARD_FROM_UPN", upn)
    to_emails = [e.strip() for e in os.environ.get("DECISION_REPORT_TO_EMAILS", "jeff@xfreight.net").split(",") if e.strip()]

    token = get_token(tenant, client, secret)
    send_email(token, from_upn, to_emails, subject, html)
    log.info("Risk & Decisions report sent to %s", ", ".join(to_emails))
    return 0


if __name__ == "__main__":
    sys.exit(main())
