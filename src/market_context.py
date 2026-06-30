"""Market context — Phase 2E (external benchmarks → brief).

Pulls free public data from FRED (St. Louis Fed) and renders a compact
benchmark panel on page 1 of the executive brief.

Live series (FRED — no API key, public CSV):
  • GASDESW    Weekly U.S. #2 retail diesel ($/gal)
  • DCOILWTICO WTI crude oil spot ($/bbl, daily) — leads diesel ~1-2wk
  • TRUCKD11   ATA Truck Tonnage Index (monthly, SA) — freight demand signal
  • WPU3012    PPI: Truck Transportation of Freight (monthly) — cost inflation
  • TSIFRGHT   BTS Freight Transportation Services Index (monthly) — direct freight volume measure
  • NAPM       ISM Manufacturing PMI (monthly) — leading demand indicator; >50 = expansion
  • RSAFS      US Retail & Food Services Sales (monthly, billions $, SA) — consumer demand → dry-van loads
  • TCU        Total Industrial Capacity Utilization (monthly, %) — >80% = tight freight market

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
_FRED_TSI_URL     = _FRED_BASE + "TSIFRGHT"    # monthly, BTS Freight TSI (2000=100)
_FRED_PMI_URL     = _FRED_BASE + "NAPM"        # monthly, ISM Mfg PMI (>50=expansion)
_FRED_RETAIL_URL  = _FRED_BASE + "RSAFS"       # monthly, US retail & food services sales (billions $, SA)
_FRED_CAPU_URL    = _FRED_BASE + "TCU"         # monthly, total industrial capacity utilization (%)

# Fuel cost constants
_ATRI_DIESEL_BASE = 3.994  # avg US retail diesel $/gal in 2023 (ATRI 2024 report period, EIA data)
_FSC_DIESEL_BASE  = 0.70   # DOE/ATA fuel surcharge formula base $/gal
_FSC_MPG_AVG      = 6.0    # industry avg mpg used in standard FSC formula

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

    # --- BTS Freight Transportation Services Index (monthly, secondary) ---
    try:
        tsi_series = _fetch_fred_csv(_FRED_TSI_URL)
        if tsi_series:
            sources["bts_freight_tsi"] = {
                "label": "BTS Freight Transportation Services Index (monthly, 2000=100)",
                "fred_series": "TSIFRGHT",
                "unit": "index",
                **_summarize(tsi_series, short_label="vs 1mo ago",
                             weeks_short=4, weeks_long=52,
                             max_gap_short_days=35, max_gap_long_days=60),
            }
        else:
            log.warning("FRED TSIFRGHT returned no rows — skipping")
    except Exception as exc:
        log.warning("FRED TSIFRGHT fetch failed: %s — skipping", exc)

    # --- ISM Manufacturing PMI (monthly, secondary) ---
    try:
        pmi_series = _fetch_fred_csv(_FRED_PMI_URL)
        if pmi_series:
            sources["ism_pmi"] = {
                "label": "ISM Manufacturing PMI (monthly, >50=expansion)",
                "fred_series": "NAPM",
                "unit": "index",
                **_summarize(pmi_series, short_label="vs 1mo ago",
                             weeks_short=4, weeks_long=52,
                             max_gap_short_days=35, max_gap_long_days=60),
            }
        else:
            log.warning("FRED NAPM returned no rows — skipping")
    except Exception as exc:
        log.warning("FRED NAPM fetch failed: %s — skipping", exc)

    # --- US Retail & Food Services Sales (monthly, secondary) ---
    try:
        retail_series = _fetch_fred_csv(_FRED_RETAIL_URL)
        if retail_series:
            sources["retail_sales"] = {
                "label": "US Retail & Food Services Sales (monthly, billions $, SA)",
                "fred_series": "RSAFS",
                "unit": "B$",
                **_summarize(retail_series, short_label="vs 1mo ago",
                             weeks_short=4, weeks_long=52,
                             max_gap_short_days=35, max_gap_long_days=60),
            }
        else:
            log.warning("FRED RSAFS returned no rows — skipping")
    except Exception as exc:
        log.warning("FRED RSAFS fetch failed: %s — skipping", exc)

    # --- Total Industrial Capacity Utilization (monthly, secondary) ---
    try:
        capu_series = _fetch_fred_csv(_FRED_CAPU_URL)
        if capu_series:
            sources["capacity_util"] = {
                "label": "Total Industrial Capacity Utilization (monthly, %)",
                "fred_series": "TCU",
                "unit": "%",
                **_summarize(capu_series, short_label="vs 1mo ago",
                             weeks_short=4, weeks_long=52,
                             max_gap_short_days=35, max_gap_long_days=60),
            }
        else:
            log.warning("FRED TCU returned no rows — skipping")
    except Exception as exc:
        log.warning("FRED TCU fetch failed: %s — skipping", exc)

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


def _compute_outlook(sources: dict) -> dict:
    """Rule-based near-term freight market outlook from FRED signals.

    Returns a dict with keys: volume, rates, fuel, summary.
    Each signal has 'label' (display text) and 'tone' (good/bad/neutral).
    """
    ata    = sources.get("ata_tonnage")     or {}
    pmi    = sources.get("ism_pmi")         or {}
    tsi    = sources.get("bts_freight_tsi") or {}
    ppi    = sources.get("ppi_trucking")    or {}
    diesel = sources.get("diesel_us")       or {}
    wti    = sources.get("wti_crude")       or {}
    retail = sources.get("retail_sales")    or {}
    capu   = sources.get("capacity_util")   or {}

    def _yoy(s):  return (s.get("yoy_52w")  or {}).get("pct_change")
    def _mom(s):  return (s.get("vs_short") or {}).get("pct_change")
    def _cur(s):  return (s.get("current")  or {}).get("value")

    ata_yoy     = _yoy(ata)
    pmi_cur     = _cur(pmi)
    tsi_yoy     = _yoy(tsi)
    ppi_yoy     = _yoy(ppi)
    diesel_yoy  = _yoy(diesel)
    diesel_4w   = _mom(diesel)
    wti_4w      = _mom(wti)
    retail_yoy  = _yoy(retail)
    capu_cur    = _cur(capu)

    signals: dict = {}

    # --- Freight volume signal (ATA tonnage YoY + ISM PMI + BTS TSI YoY + retail sales YoY + cap util) ---
    vol_votes: list[str] = []
    if ata_yoy is not None:
        vol_votes.append("expanding" if ata_yoy >= 3 else ("contracting" if ata_yoy < 0 else "flat"))
    if pmi_cur is not None:
        vol_votes.append("expanding" if pmi_cur >= 52 else ("contracting" if pmi_cur < 49 else "neutral"))
    if tsi_yoy is not None:
        vol_votes.append("expanding" if tsi_yoy >= 2 else ("contracting" if tsi_yoy < -1 else "flat"))
    if retail_yoy is not None:
        vol_votes.append("expanding" if retail_yoy >= 4 else ("contracting" if retail_yoy < 0 else "flat"))
        if retail_yoy >= 4:
            signals["retail_signal"] = f"Retail sales +{retail_yoy:.1f}% YoY — consumer demand driving dry-van loads"
        elif retail_yoy < 0:
            signals["retail_signal"] = f"Retail sales {retail_yoy:.1f}% YoY — weak consumer demand, watch for softer load volumes"
        else:
            signals["retail_signal"] = f"Retail sales +{retail_yoy:.1f}% YoY — moderate consumer demand"
    if capu_cur is not None:
        if capu_cur >= 80:
            vol_votes.append("expanding")
            signals["capu_signal"] = f"Industrial capacity utilization {capu_cur:.1f}% (≥80%) — tight industrial freight signal"
        elif capu_cur < 75:
            vol_votes.append("contracting")
            signals["capu_signal"] = f"Industrial capacity utilization {capu_cur:.1f}% (<75%) — slack industrial freight signal"
        else:
            vol_votes.append("neutral")
            signals["capu_signal"] = f"Capacity utilization {capu_cur:.1f}% (75–80% range — neutral)"
    if vol_votes:
        exp = vol_votes.count("expanding")
        con = vol_votes.count("contracting")
        if exp > con:
            signals["volume"] = {"label": "Expanding", "tone": "good",
                                 "note": "ATA tonnage / freight index trending up"}
        elif con > exp:
            signals["volume"] = {"label": "Contracting", "tone": "bad",
                                 "note": "ATA tonnage or PMI below neutral"}
        else:
            signals["volume"] = {"label": "Flat / mixed", "tone": "neutral",
                                 "note": "Mixed signals across tonnage + PMI"}

    # --- Rate environment (PPI trucking YoY = proxy for market rates) ---
    if ppi_yoy is not None:
        if ppi_yoy >= 5:
            signals["rates"] = {"label": "Rising", "tone": "good",
                                "note": f"PPI truck transportation +{ppi_yoy:.1f}% YoY"}
        elif ppi_yoy <= -2:
            signals["rates"] = {"label": "Softening", "tone": "bad",
                                "note": f"PPI truck transportation {ppi_yoy:.1f}% YoY"}
        else:
            signals["rates"] = {"label": "Stable", "tone": "neutral",
                                "note": f"PPI truck transportation {ppi_yoy:+.1f}% YoY"}

    # --- Fuel / cost pressure (diesel near-term + YoY) ---
    if diesel_yoy is not None or diesel_4w is not None:
        if (diesel_yoy or 0) >= 10:
            if (diesel_4w or 0) <= -5:
                signals["fuel"] = {"label": "Elevated but easing", "tone": "neutral",
                                   "note": "Up YoY but falling near-term"}
            else:
                signals["fuel"] = {"label": "Elevated (cost ↑)", "tone": "bad",
                                   "note": f"Diesel +{diesel_yoy:.1f}% YoY"}
        elif (diesel_yoy or 0) <= -5 or (diesel_4w or 0) <= -5:
            signals["fuel"] = {"label": "Easing (cost ↓)", "tone": "good",
                               "note": "Diesel falling — near-term cost relief"}
        else:
            signals["fuel"] = {"label": "Stable", "tone": "neutral",
                               "note": "Diesel price relatively steady"}

    # --- ISM PMI near-term demand signal (separate for color callout) ---
    if pmi_cur is not None:
        if pmi_cur >= 52:
            signals["pmi_signal"] = "Manufacturing expanding — freight demand likely to rise 30–60d"
        elif pmi_cur >= 49:
            signals["pmi_signal"] = f"PMI near neutral ({pmi_cur:.1f}) — freight demand flat near-term"
        else:
            signals["pmi_signal"] = f"PMI below 50 ({pmi_cur:.1f}) — manufacturing contracting, watch for softer volumes"

    # --- Margin squeeze: fuel costs rising faster than market rates ---
    if diesel_yoy is not None and ppi_yoy is not None:
        squeeze = diesel_yoy - ppi_yoy
        signals["margin_squeeze"] = {
            "active": squeeze > 5,
            "diesel_yoy": diesel_yoy,
            "ppi_yoy": ppi_yoy,
            "spread": round(squeeze, 1),
        }

    # --- WTI → diesel lag signal (item 5): crude moves ~1-2wk ahead of pump price ---
    if wti_4w is not None and diesel_4w is not None:
        if wti_4w <= -8 and diesel_4w > -3:
            signals["wti_lag"] = {
                "direction": "down",
                "note": (f"WTI crude fell {abs(wti_4w):.1f}% in 4wk but diesel hasn't followed"
                         f" — fuel cost relief likely in 1–2 weeks"),
            }
        elif wti_4w >= 8 and diesel_4w < 3:
            signals["wti_lag"] = {
                "direction": "up",
                "note": (f"WTI crude up {wti_4w:.1f}% in 4wk but diesel hasn't followed"
                         f" — fuel cost pressure likely in 1–2 weeks"),
            }

    # --- Seasonal context (from diesel series date → quarter) ---
    diesel_date = ((sources.get("diesel_us") or {}).get("current") or {}).get("date")
    if diesel_date:
        try:
            month = int(diesel_date[5:7])
            quarter = (month - 1) // 3 + 1
            _SEASONS = {
                1: ("Q1", "Typically soft — post-holiday inventory correction; expect rate softness"),
                2: ("Q2", "Spring pickup — freight strengthening; agricultural freight begins"),
                3: ("Q3", "Historically strong — back-to-school + retail pre-build season; pricing power window"),
                4: ("Q4", "Peak season — holiday goods + harvest freight; typically highest rates of year"),
            }
            q_label, q_note = _SEASONS[quarter]
            signals["seasonal"] = {"quarter": q_label, "note": q_note}
        except Exception:
            pass

    # --- One-line summary ---
    parts: list[str] = []
    vol_lbl  = (signals.get("volume") or {}).get("label")
    rate_lbl = (signals.get("rates")  or {}).get("label")
    fuel_lbl = (signals.get("fuel")   or {}).get("label")
    if vol_lbl:
        parts.append(f"volumes {vol_lbl.lower()}")
    if rate_lbl:
        parts.append(f"rates {rate_lbl.lower()}")
    if fuel_lbl:
        parts.append(f"fuel {fuel_lbl.lower()}")
    signals["summary"] = " · ".join(parts)
    return signals


def _compute_cost_intel(sources: dict, benchmarks: dict) -> dict:
    """Fuel sensitivity and FSC guidance from current diesel price.

    Returns est_fuel_cpm (scaled from ATRI base), fsc_per_mile (ATA formula),
    and metadata for rendering.  Returns {} if diesel price unavailable.
    """
    current_diesel = ((sources.get("diesel_us") or {}).get("current") or {}).get("value")
    if not current_diesel:
        return {}
    atri_fuel_cpm  = (benchmarks.get("fuel_cost_per_mile") or {}).get("value") or 0.593
    atri_total_cpm = (benchmarks.get("total_cost_per_mile") or {}).get("value") or 2.251
    est_fuel_cpm   = round(atri_fuel_cpm * (current_diesel / _ATRI_DIESEL_BASE), 3)
    # Break-even: replace fuel component with current-price estimate; all other costs held at ATRI baseline
    non_fuel_cpm   = atri_total_cpm - atri_fuel_cpm
    return {
        "current_diesel":   current_diesel,
        "est_fuel_cpm":     est_fuel_cpm,
        "atri_fuel_cpm":    atri_fuel_cpm,
        "atri_diesel_base": _ATRI_DIESEL_BASE,
        "fsc_per_mile":     round(max(0.0, (current_diesel - _FSC_DIESEL_BASE) / _FSC_MPG_AVG), 3),
        "breakeven_rpm":    round(non_fuel_cpm + est_fuel_cpm, 3),
        "atri_total_cpm":   atri_total_cpm,
    }


def render_chip_html(ctx: dict | None = None,
                      *,
                      ink: str = "#1a1a1a",
                      mute: str = "#6b6b6b",
                      line: str = "#ececec",
                      green: str = "#0f6b3d",
                      red: str = "#c41e2a",
                      xfreight_rpm: dict | None = None) -> str:
    """Multi-metric OTR market context panel for page 1 of the executive brief.

    Shows 6 live FRED series (diesel, WTI crude, ATA tonnage, PPI trucking,
    BTS Freight TSI, ISM Mfg PMI) plus a static ATRI industry benchmark bar,
    an optional XFreight performance row, and a rule-based near-term outlook
    section.  Hidden entirely when no cached data exists.

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
        _metric_cell("diesel_us",       "US Diesel",         fmt="${:.3f}", invert=True,  border_right=True)
        + _metric_cell("wti_crude",     "WTI Crude Oil",     fmt="${:.2f}", invert=True,  border_right=True)
        + _metric_cell("ata_tonnage",   "ATA Truck Tonnage", fmt="{:.1f}",  invert=False, border_right=True)
        + _metric_cell("ppi_trucking",  "PPI Trucking",      fmt="{:.1f}",  invert=True,  border_right=True)
        + _metric_cell("bts_freight_tsi","BTS Freight TSI",  fmt="{:.1f}",  invert=False, border_right=True)
        + _metric_cell("ism_pmi",       "ISM Mfg PMI",       fmt="{:.1f}",  invert=False, border_right=False)
    )

    # Secondary metrics row: US retail sales + capacity utilization (3 cols each)
    def _wide_cell(key: str, name: str, fmt: str, invert: bool,
                   colspan: int, border_right: bool) -> str:
        src     = sources.get(key) or {}
        current = src.get("current") or {}
        val     = current.get("value")
        asof    = current.get("date", "")
        unit    = src.get("unit", "")
        border  = f"border-right:1px solid {line};" if border_right else ""
        if val is None:
            return (
                f"<td colspan='{colspan}' style='padding:4px 10px;vertical-align:top;{border}'>"
                f"<div style='font-size:9px;color:{mute};text-transform:uppercase;"
                f"letter-spacing:1px;margin-bottom:2px;'>{name}</div>"
                f"<div style='font-size:11px;color:{mute};'>n/a</div>"
                f"</td>"
            )
        val_str    = fmt.format(val)
        vs_short   = src.get("vs_short") or {}
        vs_long    = src.get("yoy_52w") or {}
        short_lbl  = src.get("short_label", "1mo")
        short_html = _pct_span(vs_short.get("pct_change"), invert=invert)
        long_html  = _pct_span(vs_long.get("pct_change"),  invert=invert)
        return (
            f"<td colspan='{colspan}' style='padding:4px 10px;vertical-align:top;{border}'>"
            f"<div style='font-size:9px;color:{mute};text-transform:uppercase;"
            f"letter-spacing:1px;margin-bottom:2px;'>{name}</div>"
            f"<div style='font-size:12px;font-weight:700;color:{ink};'>{val_str}"
            f"<span style='font-size:10px;font-weight:400;color:{mute};'>&nbsp;{unit}</span></div>"
            f"<div style='font-size:10px;margin-top:2px;line-height:1.5;'>"
            f"{short_html}&nbsp;<span style='color:{mute};'>{short_lbl}</span>"
            f"&nbsp;&middot;&nbsp;{long_html}&nbsp;<span style='color:{mute};'>YoY</span></div>"
            f"<div style='font-size:9px;color:{mute};margin-top:1px;'>{asof}</div>"
            f"</td>"
        )

    retail_src = sources.get("retail_sales") or {}
    capu_src   = sources.get("capacity_util") or {}
    secondary_row = ""
    if retail_src or capu_src:
        secondary_row = (
            f"<tr style='border-top:1px solid {line};'>"
            + _wide_cell("retail_sales",  "US Retail Sales",    "${:.1f}",   False, 3, True)
            + _wide_cell("capacity_util", "Mfg Capacity Util.", "{:.1f}",    False, 3, False)
            + "</tr>"
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
            f"<tr><td colspan='6' style='padding:7px 10px 2px;"
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
                f"<tr><td colspan='6' style='padding:6px 10px 2px;"
                f"border-top:1px solid {line};'>"
                f"<span style='font-size:9px;font-weight:700;color:{mute};"
                f"text-transform:uppercase;letter-spacing:1px;'>XFreight Performance (MTD)</span>"
                f"<br><span style='font-size:10px;color:{ink};'>{xf_joined}</span>"
                f"</td></tr>"
            )

    # Cost intelligence row (items 1, 3): fuel sensitivity + FSC guidance
    ci = _compute_cost_intel(sources, benchmarks)
    cost_intel_html = ""
    if ci:
        est       = ci["est_fuel_cpm"]
        base      = ci["atri_fuel_cpm"]
        fsc       = ci["fsc_per_mile"]
        cur_d     = ci["current_diesel"]
        abase     = ci["atri_diesel_base"]
        breakeven = ci.get("breakeven_rpm")
        atri_tot  = ci.get("atri_total_cpm")
        fuel_color = red if est > base * 1.05 else (green if est < base * 0.97 else mute)
        breakeven_html = ""
        if breakeven and atri_tot:
            breakeven_html = (
                f"<br><span style='font-size:10px;color:{ink};'>"
                f"<b>Break-even RPM:</b>&nbsp;"
                f"<span style='font-weight:700;color:{ink};'>${breakeven:.3f}/mi</span>"
                f"&nbsp;<span style='color:{mute};'>(ATRI total ${atri_tot:.3f}/mi"
                f"&nbsp;&middot;&nbsp;fuel component scaled to today"
                f"&nbsp;&middot;&nbsp;don't take freight below this rate)</span>"
                f"</span>"
            )
        cost_intel_html = (
            f"<tr><td colspan='6' style='padding:6px 10px 4px;"
            f"border-top:1px solid {line};'>"
            f"<span style='font-size:9px;font-weight:700;color:{mute};"
            f"text-transform:uppercase;letter-spacing:1px;'>Cost Intelligence</span>"
            f"<br><span style='font-size:10px;color:{ink};'>"
            f"<b>Est. fuel cost/mi:</b>&nbsp;"
            f"<span style='color:{fuel_color};font-weight:700;'>${est:.3f}/mi</span>"
            f"&nbsp;<span style='color:{mute};'>(ATRI benchmark ${base:.3f}/mi at ${abase:.3f}/gal"
            f"&nbsp;&middot;&nbsp;scaled to current ${cur_d:.3f}/gal)</span>"
            f"&nbsp;&nbsp;&middot;&nbsp;&nbsp;"
            f"<b>Std FSC:</b>&nbsp;<span style='font-weight:700;color:{ink};'>${fsc:.3f}/mi</span>"
            f"&nbsp;<span style='color:{mute};'>(ATA: (${cur_d:.3f}&minus;$0.70)&divide;6&nbsp;mpg)</span>"
            f"</span>"
            f"{breakeven_html}"
            f"</td></tr>"
        )

    # Near-term outlook row (items 2, 4): margin squeeze + seasonal context + signals
    outlook = _compute_outlook(sources)
    outlook_html = ""
    if outlook.get("summary"):
        _tone_color = {"good": green, "bad": red, "neutral": mute}

        def _sig_chip(sig_key: str, label: str) -> str:
            sig  = outlook.get(sig_key) or {}
            lbl  = sig.get("label")
            tone = sig.get("tone", "neutral")
            note = sig.get("note", "")
            if not lbl:
                return ""
            color = _tone_color.get(tone, mute)
            note_span = (f"&nbsp;<span style='color:{mute};font-weight:400;'>"
                         f"({note})</span>") if note else ""
            return (f"<b style='color:{mute};'>{label}</b>&nbsp;"
                    f"<span style='color:{color};font-weight:700;'>{lbl}</span>"
                    f"{note_span}")

        chips = [p for p in [
            _sig_chip("volume", "Volumes:"),
            _sig_chip("rates",  "Rates:"),
            _sig_chip("fuel",   "Fuel:"),
        ] if p]

        # Margin squeeze alert (item 2)
        ms = outlook.get("margin_squeeze") or {}
        squeeze_html = ""
        if ms.get("active"):
            d_yoy = ms.get("diesel_yoy", 0)
            p_yoy = ms.get("ppi_yoy", 0)
            squeeze_html = (
                f"<br><span style='font-size:10px;color:{red};font-weight:700;'>"
                f"&#9888;&nbsp;Margin squeeze: fuel +{d_yoy:.1f}% YoY vs rates +{p_yoy:.1f}% YoY"
                f"&nbsp;&mdash;&nbsp;fuel costs rising faster than market rates</span>"
            )

        # PMI lead signal
        pmi_note = outlook.get("pmi_signal", "")
        pmi_html = (f"<br><span style='font-size:9px;color:{mute};'>"
                    f"&#8594;&nbsp;{pmi_note}</span>") if pmi_note else ""

        # Seasonal context (item 4)
        seasonal = outlook.get("seasonal") or {}
        season_html = ""
        if seasonal:
            season_html = (
                f"<br><span style='font-size:9px;color:{mute};'>"
                f"&#128197;&nbsp;<b>{seasonal['quarter']}:</b>&nbsp;{seasonal['note']}</span>"
            )

        # WTI→diesel lag signal (item 5)
        wti_lag = outlook.get("wti_lag") or {}
        wti_lag_html = ""
        if wti_lag:
            lag_color = green if wti_lag.get("direction") == "down" else red
            lag_icon  = "&#9660;" if wti_lag.get("direction") == "down" else "&#9650;"
            wti_lag_html = (
                f"<br><span style='font-size:9px;color:{lag_color};'>"
                f"{lag_icon}&nbsp;{wti_lag['note']}</span>"
            )

        # Retail sales + capacity utilization signals
        retail_sig = outlook.get("retail_signal", "")
        retail_html = (
            f"<br><span style='font-size:9px;color:{mute};'>"
            f"&#128722;&nbsp;{retail_sig}</span>"
        ) if retail_sig else ""

        capu_sig = outlook.get("capu_signal", "")
        capu_html = (
            f"<br><span style='font-size:9px;color:{mute};'>"
            f"&#127981;&nbsp;{capu_sig}</span>"
        ) if capu_sig else ""

        outlook_html = (
            f"<tr><td colspan='6' style='padding:6px 10px 4px;"
            f"border-top:1px solid {line};'>"
            f"<span style='font-size:9px;font-weight:700;color:{mute};"
            f"text-transform:uppercase;letter-spacing:1px;'>Near-Term Outlook</span>"
            f"<br><span style='font-size:10px;color:{ink};'>"
            f"{'&nbsp;&nbsp;&middot;&nbsp;&nbsp;'.join(chips)}"
            f"</span>{squeeze_html}{wti_lag_html}{pmi_html}{retail_html}{capu_html}{season_html}"
            f"</td></tr>"
        )

    generated = ctx.get("generated_at", "")
    footer_html = (
        f"<tr><td colspan='6' style='padding:4px 10px 0;'>"
        f"<span style='font-size:9px;color:{mute};'>"
        f"Source: FRED GASDESW · DCOILWTICO · TRUCKD11 · WPU3012 · TSIFRGHT · NAPM · RSAFS · TCU"
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
        f"{secondary_row}"
        f"{benchmarks_html}"
        f"{xf_html}"
        f"{cost_intel_html}"
        f"{outlook_html}"
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
