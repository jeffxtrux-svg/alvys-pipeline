"""Market context — Phase 2E (external benchmarks → brief).

Pulls free public data from FRED (St. Louis Fed) and renders a compact
benchmark panel on page 1 of the executive brief.

Live series (FRED — no API key, public CSV):
  • GASDESW    Weekly U.S. #2 retail diesel ($/gal)
  • DCOILWTICO WTI crude oil spot ($/bbl, daily) — leads diesel ~1-2wk
  • TRUCKD11   ATA Truck Tonnage Index (monthly, SA) — freight demand signal
  • WPU3012    PPI: Truck Transportation of Freight (monthly) — cost inflation

Static industry benchmarks (ATRI 2024 report, 2023 operating data):
  • Driver wages + benefits: $0.580/mi
  • Fuel cost/mi: $0.593/mi
  • Total cost/mi: $2.251/mi
  • Average operating ratio: ~96% (small–medium for-hire TL carriers)

Fail-soft: network / parse errors on non-diesel series are warnings only
(diesel failure is still a hard error since it was the original chip).
Brief reads the previous cached JSON on any failure, or renders nothing if
no cache exists.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

log = logging.getLogger("market_context")

_OUT_PATH = (Path(__file__).resolve().parent.parent
             / "Karpathy-Wiki" / "wiki" / "market-context.json")

# FRED public CSV endpoints — no API key required
_FRED_BASE        = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
_FRED_DIESEL_URL  = _FRED_BASE + "GASDESW"     # weekly, $/gal
_FRED_WTI_URL     = _FRED_BASE + "DCOILWTICO"  # daily,  $/bbl
_FRED_ATA_URL     = _FRED_BASE + "TRUCKD11"    # monthly, SA index (2015=100)
_FRED_PPI_URL     = _FRED_BASE + "WPU3012"     # monthly, index (2012=100)

# Static industry benchmarks — ATRI 2024 Annual Operational Costs of Trucking
# (covers 2023 operating data; for-hire truckload carriers, all sizes)
_INDUSTRY_BENCHMARKS: dict = {
    "driver_cost_per_mile":    {"value": 0.580, "unit": "$/mi",
                                "label": "Driver wages + benefits"},
    "fuel_cost_per_mile":      {"value": 0.593, "unit": "$/mi",
                                "label": "Fuel cost"},
    "total_cost_per_mile":     {"value": 2.251, "unit": "$/mi",
                                "label": "Total cost"},
    "avg_operating_ratio_pct": {"value": 96.0,  "unit": "%",
                                "label": "Avg operating ratio"},
    "source": "ATRI 2024 Annual Operational Costs of Trucking (2023 data · for-hire TL carriers)",
}


def _fetch_fred_csv(url: str, timeout: int = 30) -> list[tuple[date, float]]:
    """Fetch a FRED series CSV and return [(date, value), ...].
    Drops rows where value isn't parseable (FRED uses '.' for missing)."""
    log.info("Fetching FRED CSV: %s", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    rows: list[tuple[date, float]] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        date_str = row.get("observation_date") or row.get("DATE")
        value_str = None
        for k, v in row.items():
            if k and k not in ("observation_date", "DATE"):
                value_str = v
                break
        if not date_str or value_str is None:
            continue
        try:
            d = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            continue
        try:
            v_float = float(value_str.strip())
        except (ValueError, AttributeError):
            continue  # FRED uses '.' for missing
        rows.append((d, v_float))
    return rows


def _summarize(series: list[tuple[date, float]],
               short_label: str = "vs 4wk ago",
               weeks_short: int = 4,
               weeks_long: int = 52,
               max_gap_short_days: int = 21,
               max_gap_long_days: int = 40) -> dict:
    """Reduce a time-series to current / short-term / long-term snapshot.

    Uses date arithmetic rather than index offsets so the same function
    works correctly for daily (WTI), weekly (diesel), and monthly (ATA/PPI)
    series without needing cadence-specific logic.
    """
    if not series:
        return {}
    series = sorted(series, key=lambda r: r[0])
    latest_date, latest_value = series[-1]
    out: dict = {
        "current": {
            "date": latest_date.isoformat(),
            "value": round(latest_value, 3),
        },
        "short_label": short_label,
    }
    # Short-term comparison
    target_s = latest_date - timedelta(weeks=weeks_short)
    closest_s = min(series, key=lambda r: abs((r[0] - target_s).days))
    ds, vs = closest_s
    if abs((ds - target_s).days) <= max_gap_short_days:
        out["vs_short"] = {
            "date": ds.isoformat(),
            "value": round(vs, 3),
            "pct_change": round((latest_value - vs) / vs * 100, 2) if vs else None,
        }
    # Long-term / YoY comparison
    target_l = latest_date - timedelta(weeks=weeks_long)
    closest_l = min(series, key=lambda r: abs((r[0] - target_l).days))
    dl, vl = closest_l
    if abs((dl - target_l).days) <= max_gap_long_days:
        out["yoy_52w"] = {
            "date": dl.isoformat(),
            "value": round(vl, 3),
            "pct_change": round((latest_value - vl) / vl * 100, 2) if vl else None,
        }
    return out


def fetch_and_write(out_path: Path | None = None) -> bool:
    """Pull fresh data from all FRED series and write the JSON cache file.

    Returns True only if the primary diesel series succeeded.  Secondary
    series (WTI, ATA, PPI) are fail-soft warnings.
    """
    out_path = out_path or _OUT_PATH
    primary_ok = True
    sources: dict = {}

    # --- US Diesel (weekly, primary) ---
    try:
        diesel_series = _fetch_fred_csv(_FRED_DIESEL_URL)
        if diesel_series:
            sources["diesel_us"] = {
                "label": "US #2 retail diesel ($/gal, weekly avg)",
                "fred_series": "GASDESW",
                "unit": "$/gal",
                **_summarize(diesel_series, short_label="vs 4wk ago",
                             weeks_short=4, weeks_long=52,
                             max_gap_short_days=14, max_gap_long_days=21),
            }
        else:
            log.error("FRED GASDESW returned no parseable rows")
            primary_ok = False
    except Exception as exc:
        log.error("FRED GASDESW fetch failed: %s", exc)
        primary_ok = False

    # --- WTI Crude Oil (daily, secondary) ---
    try:
        wti_series = _fetch_fred_csv(_FRED_WTI_URL)
        if wti_series:
            sources["wti_crude"] = {
                "label": "WTI crude oil ($/bbl, daily spot)",
                "fred_series": "DCOILWTICO",
                "unit": "$/bbl",
                **_summarize(wti_series, short_label="vs 4wk ago",
                             weeks_short=4, weeks_long=52,
                             max_gap_short_days=7, max_gap_long_days=14),
            }
        else:
            log.warning("FRED DCOILWTICO returned no rows — skipping")
    except Exception as exc:
        log.warning("FRED DCOILWTICO fetch failed: %s — skipping", exc)

    # --- ATA Truck Tonnage Index (monthly, secondary) ---
    try:
        ata_series = _fetch_fred_csv(_FRED_ATA_URL)
        if ata_series:
            sources["ata_tonnage"] = {
                "label": "ATA Truck Tonnage Index (monthly, SA, 2015=100)",
                "fred_series": "TRUCKD11",
                "unit": "index",
                **_summarize(ata_series, short_label="vs 1mo ago",
                             weeks_short=4, weeks_long=52,
                             max_gap_short_days=35, max_gap_long_days=60),
            }
        else:
            log.warning("FRED TRUCKD11 returned no rows — skipping")
    except Exception as exc:
        log.warning("FRED TRUCKD11 fetch failed: %s — skipping", exc)

    # --- PPI: Truck Transportation (monthly, secondary) ---
    try:
        ppi_series = _fetch_fred_csv(_FRED_PPI_URL)
        if ppi_series:
            sources["ppi_trucking"] = {
                "label": "PPI: Truck Transportation of Freight (monthly, 2012=100)",
                "fred_series": "WPU3012",
                "unit": "index",
                **_summarize(ppi_series, short_label="vs 1mo ago",
                             weeks_short=4, weeks_long=52,
                             max_gap_short_days=35, max_gap_long_days=60),
            }
        else:
            log.warning("FRED WPU3012 returned no rows — skipping")
    except Exception as exc:
        log.warning("FRED WPU3012 fetch failed: %s — skipping", exc)

    payload = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "sources": sources,
        "industry_benchmarks": _INDUSTRY_BENCHMARKS,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    log.info("Wrote %s (%d bytes) — series: %s",
             out_path, len(out_path.read_bytes()), ", ".join(sources))
    return primary_ok


def load_cached(path: Path | None = None) -> dict:
    """Return the cached market-context dict, or {} if missing/malformed."""
    p = path or _OUT_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        log.warning("market_context: failed to parse %s (%s)", p, exc)
        return {}


def render_chip_html(ctx: dict | None = None,
                      *,
                      ink: str = "#1a1a1a",
                      mute: str = "#6b6b6b",
                      line: str = "#ececec",
                      green: str = "#0f6b3d",
                      red: str = "#c41e2a",
                      xfreight_rpm: dict | None = None) -> str:
    """Multi-metric OTR market context panel for page 1 of the executive brief.

    Shows 4 live FRED series (diesel, WTI crude, ATA tonnage, PPI trucking)
    plus a static ATRI industry benchmark bar and an optional XFreight
    performance row comparing actual RPM to the ATRI total-cost benchmark and
    the internal cost-out goal.  Hidden entirely when no cached data exists.

    Args:
        xfreight_rpm: dict from ``compute_rpm_goal`` — keys ``actual_rpm``,
            ``goal_rpm``, ``cost_per_mile``, ``gap`` (goal minus actual).
    """
    ctx = ctx if ctx is not None else load_cached()
    sources = ctx.get("sources") or {}
    benchmarks = ctx.get("industry_benchmarks") or {}
    if not sources:
        return ""

    def _pct_span(pct, invert: bool = False) -> str:
        """Colored ▲/▼ % span. invert=True = down is good (costs, prices)."""
        if pct is None:
            return f"<span style='color:{mute}'>n/a</span>"
        up   = pct >  0.5
        down = pct < -0.5
        if invert:
            color = green if down else (red if up else mute)
        else:
            color = red if down else (green if up else mute)
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
        return (f"<span style='color:{color};font-weight:700;'>"
                f"{arrow}&nbsp;{abs(pct):.1f}%</span>")

    def _metric_cell(key: str, name: str, fmt: str = "{:.2f}",
                     invert: bool = False, border_right: bool = True) -> str:
        src     = sources.get(key) or {}
        current = src.get("current") or {}
        val     = current.get("value")
        asof    = current.get("date", "")
        unit    = src.get("unit", "")
        border  = f"border-right:1px solid {line};" if border_right else ""

        if val is None:
            return (
                f"<td style='padding:6px 10px;vertical-align:top;{border}'>"
                f"<div style='font-size:9px;color:{mute};text-transform:uppercase;"
                f"letter-spacing:1px;margin-bottom:3px;'>{name}</div>"
                f"<div style='font-size:11px;color:{mute};'>n/a</div>"
                f"</td>"
            )

        val_str   = fmt.format(val)
        vs_short  = src.get("vs_short") or src.get("wow_4w") or {}  # wow_4w = legacy key
        vs_long   = src.get("yoy_52w") or {}
        short_lbl = src.get("short_label", "4wk")

        short_html = _pct_span(vs_short.get("pct_change"), invert=invert)
        long_html  = _pct_span(vs_long.get("pct_change"),  invert=invert)

        return (
            f"<td style='padding:6px 10px;vertical-align:top;{border}'>"
            f"<div style='font-size:9px;color:{mute};text-transform:uppercase;"
            f"letter-spacing:1px;margin-bottom:3px;'>{name}</div>"
            f"<div style='font-size:13px;font-weight:700;color:{ink};'>{val_str}"
            f"<span style='font-size:10px;font-weight:400;color:{mute};'>&nbsp;{unit}</span></div>"
            f"<div style='font-size:10px;margin-top:2px;line-height:1.5;'>"
            f"{short_html}&nbsp;<span style='color:{mute};'>{short_lbl}</span>"
            f"&nbsp;&middot;&nbsp;{long_html}&nbsp;<span style='color:{mute};'>YoY</span></div>"
            f"<div style='font-size:9px;color:{mute};margin-top:1px;'>{asof}</div>"
            f"</td>"
        )

    # as-of date from diesel (most current weekly), fall back to WTI
    asof_label = (
        ((sources.get("diesel_us") or {}).get("current") or {}).get("date")
        or ((sources.get("wti_crude") or {}).get("current") or {}).get("date")
        or ""
    )

    metrics_row = (
        _metric_cell("diesel_us",    "US Diesel",        fmt="${:.3f}", invert=True,  border_right=True)
        + _metric_cell("wti_crude",  "WTI Crude Oil",    fmt="${:.2f}", invert=True,  border_right=True)
        + _metric_cell("ata_tonnage","ATA Truck Tonnage",fmt="{:.1f}",  invert=False, border_right=True)
        + _metric_cell("ppi_trucking","PPI Trucking",    fmt="{:.1f}",  invert=True,  border_right=False)
    )

    # Industry benchmarks bar
    bm_parts: list[str] = []
    for key, label in [
        ("driver_cost_per_mile",    "Driver cost"),
        ("fuel_cost_per_mile",      "Fuel cost"),
        ("total_cost_per_mile",     "Total cost/mi"),
        ("avg_operating_ratio_pct", "Avg OR"),
    ]:
        bm = benchmarks.get(key) or {}
        val = bm.get("value")
        unit = bm.get("unit", "")
        if val is None:
            continue
        if unit == "$/mi":
            val_fmt = f"${val:.3f}/mi"
        elif unit == "%":
            val_fmt = f"{val:.0f}%"
        else:
            val_fmt = f"{val}"
        bm_parts.append(f"{label}&nbsp;<b>{val_fmt}</b>")

    bm_source = benchmarks.get("source", "ATRI 2024")
    benchmarks_html = ""
    if bm_parts:
        bm_joined = "&nbsp;&nbsp;·&nbsp;&nbsp;".join(bm_parts)
        benchmarks_html = (
            f"<tr><td colspan='4' style='padding:7px 10px 2px;"
            f"border-top:1px solid {line};'>"
            f"<span style='font-size:9px;font-weight:700;color:{mute};"
            f"text-transform:uppercase;letter-spacing:1px;'>Industry Benchmarks</span>"
            f"&nbsp;<span style='font-size:9px;color:{mute};'>({bm_source})</span>"
            f"<br><span style='font-size:10px;color:{ink};'>{bm_joined}</span>"
            f"</td></tr>"
        )

    # XFreight performance row — actual RPM vs ATRI total cost and internal goal
    xf_html = ""
    if xfreight_rpm:
        actual   = xfreight_rpm.get("actual_rpm")
        goal     = xfreight_rpm.get("goal_rpm")
        atri_bm  = (benchmarks.get("total_cost_per_mile") or {}).get("value")
        if actual:
            parts_xf: list[str] = [
                f"Actual RPM&nbsp;<b>${actual:.2f}/mi</b>"
            ]
            if atri_bm:
                spread_vs_atri = actual - atri_bm
                atri_color = green if spread_vs_atri >= 0 else red
                atri_arrow = "▲" if spread_vs_atri >= 0 else "▼"
                parts_xf.append(
                    f"ATRI total cost&nbsp;<b>${atri_bm:.3f}/mi</b>"
                    f"&nbsp;→&nbsp;"
                    f"<span style='color:{atri_color};font-weight:700;'>"
                    f"{atri_arrow}&nbsp;${abs(spread_vs_atri):.2f}/mi "
                    f"{'above' if spread_vs_atri >= 0 else 'below'} cost</span>"
                )
            if goal:
                gap = goal - actual   # positive = behind goal
                goal_color = green if gap <= 0 else red
                goal_arrow = "▼" if gap > 0 else "▲"
                parts_xf.append(
                    f"Goal&nbsp;<b>${goal:.2f}/mi</b>"
                    f"&nbsp;→&nbsp;"
                    f"<span style='color:{goal_color};font-weight:700;'>"
                    f"{goal_arrow}&nbsp;${abs(gap):.2f}/mi "
                    f"{'behind' if gap > 0 else 'above'} goal</span>"
                )
            xf_joined = "&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts_xf)
            xf_html = (
                f"<tr><td colspan='4' style='padding:6px 10px 2px;"
                f"border-top:1px solid {line};'>"
                f"<span style='font-size:9px;font-weight:700;color:{mute};"
                f"text-transform:uppercase;letter-spacing:1px;'>XFreight Performance (MTD)</span>"
                f"<br><span style='font-size:10px;color:{ink};'>{xf_joined}</span>"
                f"</td></tr>"
            )

    generated = ctx.get("generated_at", "")
    footer_html = (
        f"<tr><td colspan='4' style='padding:4px 10px 0;'>"
        f"<span style='font-size:9px;color:{mute};'>"
        f"Source: FRED GASDESW · DCOILWTICO · TRUCKD11 · WPU3012"
        f"{(' · refreshed ' + generated[:10]) if generated else ''}"
        f"</span></td></tr>"
    )

    asof_display = f" ({asof_label})" if asof_label else ""
    return (
        f"<div style='margin:0 0 14px;padding:10px 14px;background:#fcfcfc;"
        f"border:1px solid {line};border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{mute};text-transform:uppercase;margin-bottom:8px;'>"
        f"Market Context · OTR Truckload{asof_display}</div>"
        f"<table style='width:100%;border-collapse:collapse;'>"
        f"<tr>{metrics_row}</tr>"
        f"{benchmarks_html}"
        f"{xf_html}"
        f"{footer_html}"
        f"</table>"
        f"</div>"
    )


def main() -> int:
    """CLI entry — runs the full fetch + write."""
    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                         datefmt="%H:%M:%S")
    ok = fetch_and_write()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
