"""Market context — Phase 2E (external benchmarks → brief).

Pulls the weekly US #2 retail diesel price from FRED (St. Louis Fed,
series GASDESW) — free public CSV, no API key. Computes current price +
week-over-week change + 52-week comparison and writes a small JSON file
the brief reads each morning to render a "Market Context" chip on page 1.

Why this matters: today the brief's "actual RPM" sits on the page with
no market frame. If actual RPM dropped 8¢ MTD that could be a problem
OR it could be the market dropping further (XFreight outperforming).
Diesel price especially: an 8% fuel run-up is the difference between
"profitable" and "underwater" on contract rates without a FSC clause —
without the market number on the brief, the cause is invisible.

Source: FRED GASDESW (Weekly U.S. Diesel Retail Price, $/gallon).
URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id=GASDESW

DAT spot rate is intentionally NOT included in v1 — requires a paid DAT
account. Add later under the same `market` dict in market-context.json
if/when we onboard DAT.

Fail-soft: network error, parse error, malformed response — script
exits non-zero with a logged error; the brief reads the previous
cached JSON (or renders nothing if no cache exists).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

import requests

log = logging.getLogger("market_context")

_OUT_PATH = (Path(__file__).resolve().parent.parent
             / "Karpathy-Wiki" / "wiki" / "market-context.json")

_FRED_DIESEL_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GASDESW"


def _fetch_fred_csv(url: str, timeout: int = 30) -> list[tuple[date, float]]:
    """Fetch a FRED weekly series CSV and return [(date, value), ...].
    Drops rows where value isn't parseable (FRED uses '.' for missing)."""
    log.info("Fetching FRED CSV: %s", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    rows: list[tuple[date, float]] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        # FRED schemas vary slightly — date col is usually 'observation_date',
        # value col matches the series id.
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
            v = float(value_str.strip())
        except (ValueError, AttributeError):
            continue  # FRED uses '.' for missing
        rows.append((d, v))
    return rows


def _summarize(series: list[tuple[date, float]]) -> dict:
    """Reduce a weekly time-series to current / 4w-ago / 52w-ago snapshot."""
    if not series:
        return {}
    series = sorted(series, key=lambda r: r[0])
    latest_date, latest_value = series[-1]
    out: dict = {
        "current": {
            "date": latest_date.isoformat(),
            "value": round(latest_value, 3),
        },
    }
    # 4-week-ago (index from end)
    if len(series) >= 5:
        d4, v4 = series[-5]
        out["wow_4w"] = {
            "date": d4.isoformat(),
            "value": round(v4, 3),
            "pct_change": round((latest_value - v4) / v4 * 100, 2) if v4 else None,
        }
    # 52-week-ago
    if len(series) >= 53:
        d52, v52 = series[-53]
        out["yoy_52w"] = {
            "date": d52.isoformat(),
            "value": round(v52, 3),
            "pct_change": round((latest_value - v52) / v52 * 100, 2) if v52 else None,
        }
    return out


def fetch_and_write(out_path: Path | None = None) -> bool:
    """Pull fresh data + write the JSON file. Returns True on success."""
    out_path = out_path or _OUT_PATH
    try:
        diesel_series = _fetch_fred_csv(_FRED_DIESEL_URL)
    except Exception as exc:
        log.error("FRED diesel fetch failed: %s", exc)
        return False
    if not diesel_series:
        log.error("FRED diesel CSV returned no parseable rows")
        return False

    payload = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "sources": {
            "diesel_us": {
                "label": "US #2 retail diesel ($/gal, weekly avg)",
                "fred_series": "GASDESW",
                "url": _FRED_DIESEL_URL,
                **_summarize(diesel_series),
            },
        },
        # Reserved for future sources — DAT spot rate, AAA gas avg, etc.
        # Add new top-level keys under `sources` without breaking the brief reader.
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    log.info("Wrote %s (%d bytes)", out_path, len(out_path.read_bytes()))
    return True


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
                      red: str = "#c41e2a") -> str:
    """Compact chip for page 1 showing diesel price + WoW change. Hidden
    when the cache is empty or malformed."""
    ctx = ctx if ctx is not None else load_cached()
    diesel = (ctx.get("sources") or {}).get("diesel_us") or {}
    current = diesel.get("current") or {}
    if not current.get("value"):
        return ""
    price = current["value"]
    asof = current.get("date", "")

    wow = diesel.get("wow_4w") or {}
    wow_pct = wow.get("pct_change")
    if wow_pct is not None:
        wow_color = red if wow_pct > 0.5 else (green if wow_pct < -0.5 else mute)
        wow_arrow = "▲" if wow_pct > 0 else ("▼" if wow_pct < 0 else "—")
        wow_text = (f"<span style='color:{wow_color};font-weight:700;'>"
                    f"{wow_arrow} {abs(wow_pct):.1f}%</span> "
                    f"<span style='color:{mute};font-size:10px;'>vs 4wk ago</span>")
    else:
        wow_text = f"<span style='color:{mute};font-size:10px;'>4wk Δ unavailable</span>"

    yoy = diesel.get("yoy_52w") or {}
    yoy_pct = yoy.get("pct_change")
    yoy_text = ""
    if yoy_pct is not None:
        yoy_color = red if yoy_pct > 0.5 else (green if yoy_pct < -0.5 else mute)
        yoy_arrow = "▲" if yoy_pct > 0 else ("▼" if yoy_pct < 0 else "—")
        yoy_text = (f" &middot; <span style='color:{yoy_color};font-weight:700;'>"
                    f"{yoy_arrow} {abs(yoy_pct):.1f}%</span> "
                    f"<span style='color:{mute};font-size:10px;'>YoY</span>")

    return (
        f"<div style='margin:0 0 14px;padding:10px 14px;background:#fcfcfc;"
        f"border:1px solid {line};border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{mute};text-transform:uppercase;margin-bottom:6px;'>"
        f"Market Context · US Diesel ({asof})</div>"
        f"<div style='font-size:14px;color:{ink};'>"
        f"<span style='font-weight:700;'>${price:.3f}/gal</span> &middot; "
        f"{wow_text}{yoy_text}"
        f"</div>"
        f"<div style='margin-top:4px;color:{mute};font-size:10px;'>"
        f"Source: FRED series GASDESW (weekly U.S. avg #2 retail diesel)."
        f"</div>"
        f"</div>"
    )


def main() -> int:
    """CLI entry — runs the weekly fetch + write."""
    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                         datefmt="%H:%M:%S")
    ok = fetch_and_write()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
