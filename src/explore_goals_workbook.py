"""One-off: read the 'Goals and Trends' workbook from OneDrive and email back
its structure (sheet names, dimensions, column headers, sample rows) so the
cost-per-mile algorithm can be designed against the actual columns instead of
guessed at.

No analysis — just enumeration. Disposable script.
"""
from __future__ import annotations

import io
import logging
import os
import sys

import pandas as pd
from dotenv import load_dotenv

from src.onedrive_upload import download_shared_file, get_token
from src.scorecard_email import send_email

log = logging.getLogger("explore_goals_workbook")

MAX_HEAD_ROWS = 8
MAX_TAIL_ROWS = 3
MAX_COL_WIDTH = 22


def _cell(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if len(s) > MAX_COL_WIDTH:
        s = s[: MAX_COL_WIDTH - 1] + "…"
    return s


def _render_sheet(name: str, df: pd.DataFrame) -> str:
    lines: list[str] = []
    lines.append(f"=== Sheet: '{name}' — {df.shape[0]} rows x {df.shape[1]} cols ===")
    if df.empty:
        lines.append("(empty)")
        return "\n".join(lines)

    cols = list(df.columns)
    lines.append("Columns:")
    for i, c in enumerate(cols):
        lines.append(f"  [{i:>2}] {c!r}")

    head = df.head(MAX_HEAD_ROWS)
    tail = df.tail(MAX_TAIL_ROWS) if len(df) > MAX_HEAD_ROWS + MAX_TAIL_ROWS else None

    def fmt_rows(frame: pd.DataFrame) -> list[str]:
        widths = [
            min(MAX_COL_WIDTH, max(len(_cell(c)), *(len(_cell(v)) for v in frame[c])))
            for c in frame.columns
        ]
        header = "  " + "  ".join(_cell(c).ljust(widths[i]) for i, c in enumerate(frame.columns))
        body = []
        for _, row in frame.iterrows():
            body.append("  " + "  ".join(_cell(row[c]).ljust(widths[i])
                                          for i, c in enumerate(frame.columns)))
        return [header] + body

    lines.append("")
    lines.append(f"First {min(MAX_HEAD_ROWS, len(df))} rows:")
    lines.extend(fmt_rows(head))
    if tail is not None:
        lines.append("")
        lines.append(f"Last {MAX_TAIL_ROWS} rows:")
        lines.extend(fmt_rows(tail))
    return "\n".join(lines)


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
    share_url = os.environ.get("GOALS_TRENDS_SHARE_URL", "").strip()
    if not all([tenant, client, secret, upn, share_url]):
        sys.exit("ERROR: AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET, ONEDRIVE_USER_UPN, "
                 "and GOALS_TRENDS_SHARE_URL are required")

    from_upn = os.environ.get("SCORECARD_FROM_UPN", upn)
    to_emails = [e.strip() for e in os.environ.get("SCORECARD_TO_EMAILS", "jeff@xfreight.net").split(",")
                 if e.strip()]

    token = get_token(tenant, client, secret)
    log.info("Downloading workbook via share URL")
    raw = download_shared_file(token, share_url)
    sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None)
    log.info("Workbook has %d sheets: %s", len(sheets), list(sheets.keys()))

    sections: list[str] = []
    sections.append(f"Workbook structure dump")
    sections.append(f"{'=' * 60}")
    sections.append(f"Sheets ({len(sheets)}): {', '.join(sheets.keys())}")
    sections.append("")
    for name, df in sheets.items():
        sections.append(_render_sheet(name, df))
        sections.append("")
    report = "\n".join(sections)
    log.info("\n%s", report)

    html = "<pre style='font-family:Consolas,Menlo,monospace;font-size:11px;'>" + (
        report.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ) + "</pre>"
    subject = f"Goals & Trends workbook — structure dump"
    send_email(token, from_upn, to_emails, subject, html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
