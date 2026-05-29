"""Generate a markdown summary of a pipeline pull and archive it.

Each pull (Alvys / Samsara / QuickBooks / Sheets) calls this after producing
its .xlsx output, so the run shows up in Karpathy-Wiki/raw/ even though the
raw binaries themselves are not committed.

Usage:
    python -m src.write_run_summary alvys output/Alvys_Master.xlsx
    python -m src.write_run_summary samsara output/samsara/Samsara_Master.xlsx
    python -m src.write_run_summary qb output/quickbooks
    python -m src.write_run_summary sheets
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd

from src.karpathy_writer import frontmatter, save

log = logging.getLogger("write_run_summary")


def _kpi_line(label: str, value: str) -> str:
    return f"- **{label}**: {value}"


def _money(v) -> str:
    return f"${v:,.0f}" if pd.notna(v) and isinstance(v, (int, float)) else "n/a"


def alvys_summary(path: str) -> str:
    sheets = pd.read_excel(path, sheet_name=None)
    loads = sheets.get("Loads", pd.DataFrame())
    lines = [frontmatter("Alvys refresh", "alvys-pull",
                         workbook=os.path.basename(path),
                         loads=str(len(loads)))]
    lines.append("# Alvys refresh summary\n")
    lines.append(_kpi_line("Workbook", f"`{os.path.basename(path)}`"))
    lines.append(_kpi_line("Sheets", ", ".join(sheets.keys())))
    if not loads.empty:
        lines.append(_kpi_line("Loads", f"{len(loads):,} rows × {len(loads.columns)} cols"))
        if "Customer Revenue" in loads.columns:
            tot = pd.to_numeric(loads["Customer Revenue"], errors="coerce").sum()
            lines.append(_kpi_line("Total Customer Revenue (all-time)", _money(tot)))
        if "Driver Rate" in loads.columns:
            tot = pd.to_numeric(loads["Driver Rate"], errors="coerce").sum()
            lines.append(_kpi_line("Total Driver Rate (all-time)", _money(tot)))
        if "Load Status" in loads.columns:
            vc = loads["Load Status"].astype(str).value_counts()
            lines.append("\n## Load Status distribution\n")
            for k, v in vc.head(10).items():
                lines.append(f"- {k}: {v:,}")
    for tab in ("Trips", "Fuel", "Carriers", "Customers", "Drivers"):
        if tab in sheets and not sheets[tab].empty:
            df = sheets[tab]
            lines.append(f"\n## {tab}: {len(df):,} rows × {len(df.columns)} cols\n")
    return "\n".join(lines)


def samsara_summary(path: str) -> str:
    sheets = pd.read_excel(path, sheet_name=None)
    lines = [frontmatter("Samsara refresh", "samsara-pull",
                         workbook=os.path.basename(path))]
    lines.append("# Samsara refresh summary\n")
    lines.append(_kpi_line("Workbook", f"`{os.path.basename(path)}`"))
    lines.append(_kpi_line("Sheets", ", ".join(sheets.keys())))
    for name, df in sheets.items():
        lines.append(f"\n## {name}: {len(df):,} rows × {len(df.columns)} cols")
    return "\n".join(lines)


def qb_summary(directory: str) -> str:
    path = Path(directory)
    files = sorted(path.glob("QB_*.xlsx")) if path.exists() else []
    lines = [frontmatter("QuickBooks refresh", "qb-pull",
                         directory=str(directory),
                         files=str(len(files)))]
    lines.append("# QuickBooks refresh summary\n")
    lines.append(_kpi_line("Output directory", f"`{directory}`"))
    lines.append(_kpi_line("Files", str(len(files))))
    if not files:
        return "\n".join(lines)
    lines.append("\n## Files\n")
    for f in files:
        try:
            sheets = pd.read_excel(f, sheet_name=None)
            total_rows = sum(len(df) for df in sheets.values())
            lines.append(f"- `{f.name}`: {len(sheets)} sheets, {total_rows:,} rows total")
        except Exception as exc:
            lines.append(f"- `{f.name}`: (read error: {exc})")
    return "\n".join(lines)


def sheets_summary() -> str:
    lines = [frontmatter("Google Sheets KPI dashboard refresh", "sheets-pull")]
    lines.append("# Google Sheets KPI dashboard refresh\n")
    lines.append("Pipeline ran end-to-end (Alvys + Samsara + QuickBooks → Sheets).")
    lines.append("Detailed tab counts are in the workflow log on this run.")
    return "\n".join(lines)


SUMMARIZERS = {
    "alvys": alvys_summary,
    "samsara": samsara_summary,
    "qb": qb_summary,
    "sheets": lambda _path=None: sheets_summary(),
}


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    if len(sys.argv) < 2 or sys.argv[1] not in SUMMARIZERS:
        sys.exit(f"usage: write_run_summary <{'|'.join(SUMMARIZERS)}> [path]")
    source = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        content = SUMMARIZERS[source](path) if path else SUMMARIZERS[source]()
    except Exception as exc:
        log.warning("Summary generation failed for %s: %s", source, exc)
        content = frontmatter(f"{source} refresh (error)", f"{source}-pull") + \
                  f"# {source} refresh\n\nSummary generation failed: {exc}\n"
    save(source, f"{source}-refresh", content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
