"""Rule-based insight generation for the executive brief — the $0
alternative to the LLM reviewer.

Generates three things from the day's computed KPIs:

  * bottom_line(...)     -> one-paragraph signal for the top of page 1
  * action_items(...)    -> 0-3 'act today' cards, severity-coded
  * coaching_cards(...)  -> per-driver talk tracks for the worst idlers
  * page_strips(...)     -> per-page contextual notes (pages 2-10)

Templates are quantitative — they plug in the live numbers — and reference
the methodology in `docs/knowledge-base/` rather than restating it. The
output reads as written-for-today even though the wording is templated.

Add a new pattern by:
  1. Writing a function that returns a string or `None`
  2. Listing it in the generator that should call it
  3. Order matters — the first non-None wins for action items, since
     we cap the list at 3.

All money / percent / number formatting goes through the same `money`,
`pct`, `num` helpers `scorecard_email.py` uses, imported lazily so this
module doesn't pull a hard dependency on the renderer.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def _isnum(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _money(v) -> str:
    if not _isnum(v):
        return "n/a"
    v = float(v)
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _pct(v) -> str:
    if not _isnum(v):
        return "n/a"
    return f"{float(v) * 100:.1f}%"


def _num(v) -> str:
    if not _isnum(v):
        return "n/a"
    return f"{float(v):,.0f}"


# Tuning constants — change here without hunting through templates.
IDLE_GPH = 0.8                # fleet-average idle burn (Class-8 sleeper)
DIESEL_PRICE = 3.80           # $/gal — refresh quarterly
WEEKS_PER_MONTH = 4.33
XLINX_MARGIN_GOAL = 0.175     # X-Linx brokerage margin target (revenue − carrier pay)


# ----------------------------------------------------------------------
# Bottom line — one paragraph at the top of page 1
# ----------------------------------------------------------------------
def bottom_line(*, alvys: dict | None, qb_pnl: dict | None,
                samsara: dict | None, rpm_goal: dict | None,
                margin_projection: dict | None,
                qb_ar: dict | None, ar_hist: tuple | None = None,
                samba: dict | None = None,
                alvys_entities: dict | None = None) -> str:
    """Generate the bottom-line paragraph. Joins 3-4 sentences picked
    from threshold-triggered templates."""
    parts: list[str] = []

    mtd_label = (alvys or {}).get("mtd_label", "MTD")
    ents = alvys_entities or {}

    # X-Trux lead — asset trucking. Margin % here is driver-pay share of
    # revenue (Driver Rate ÷ Revenue), so a lower number is better. RPM is
    # the optimization target — see the next sentence.
    xt = ents.get("X-Trux") or {}
    xt_rev = xt.get("revenue")
    xt_mgn = xt.get("margin_pct")
    if _isnum(xt_rev) and _isnum(xt_mgn):
        parts.append(
            f"X-Trux {mtd_label}: {_money(xt_rev)} revenue, "
            f"{_pct(xt_mgn)} margin (driver-pay share of revenue).")

    # X-Linx lead — brokerage. Target margin is 17.5% (carrier-pay net).
    xl = ents.get("X-Linx") or {}
    xl_rev = xl.get("revenue")
    xl_mgn = xl.get("margin_pct")
    if _isnum(xl_rev) and _isnum(xl_mgn):
        delta = xl_mgn - XLINX_MARGIN_GOAL
        verdict = (f"above the {_pct(XLINX_MARGIN_GOAL)} goal"
                   if delta >= 0
                   else f"{_pct(abs(delta))} below the {_pct(XLINX_MARGIN_GOAL)} goal")
        parts.append(
            f"X-Linx {mtd_label}: {_money(xl_rev)} revenue, "
            f"{_pct(xl_mgn)} margin ({verdict}).")

    # Fallback to combined MTD line only if neither entity had data — keeps
    # the brief non-empty for any historical run where the entity split is
    # unavailable.
    if not parts:
        mtd = (alvys or {}).get("mtd") or {}
        rev = mtd.get("revenue")
        margin_pct = mtd.get("margin_pct")
        if _isnum(rev) and _isnum(margin_pct):
            parts.append(
                f"{mtd_label} closed at {_money(rev)} revenue and "
                f"{_pct(margin_pct)} margin.")

    # X-Trux RPM gap → annualized uplift potential. Brokerage is per-load
    # not per-mile so the goal does not apply to X-Linx.
    if rpm_goal:
        actual = rpm_goal.get("actual_rpm")
        goal = rpm_goal.get("goal_rpm")
        # Prefer X-Trux miles; fall back to combined if asset split missing.
        miles_mtd = (((alvys or {}).get("asset") or {}).get("mtd") or {}).get("miles") \
            or ((alvys or {}).get("mtd") or {}).get("miles") or 0
        if _isnum(actual) and _isnum(goal) and actual < goal and miles_mtd:
            gap = goal - actual
            annual_uplift = gap * miles_mtd * 12
            parts.append(
                f"X-Trux RPM ${actual:.2f} vs ${goal:.2f} goal; closing that gap "
                f"≈ {_money(annual_uplift)} of annual margin uplift "
                f"(per rate-per-mile-goal methodology).")

    # Idle cost — biggest unmonetized expense for most fleets.
    if samsara and samsara.get("fleet"):
        idle_h = samsara["fleet"].get("fleet_idle_hours")
        if _isnum(idle_h) and idle_h > 1000:
            weekly_fuel = (idle_h * IDLE_GPH * DIESEL_PRICE) / WEEKS_PER_MONTH
            parts.append(
                f"Biggest lever is idle: {_num(idle_h)} hrs in the window "
                f"(~{_money(weekly_fuel)}/wk of fuel at "
                f"{IDLE_GPH} gph × ${DIESEL_PRICE}/gal).")

    # AR trend — only mention if the trajectory is up.
    if ar_hist and len(ar_hist) == 2:
        labels, values = ar_hist
        if values and len(values) >= 2:
            first, last = values[0], values[-1]
            if _isnum(first) and _isnum(last) and last > first * 1.15:
                parts.append(
                    f"AR climbed {_money(last - first)} over "
                    f"{len(values)} months ({_money(first)} → {_money(last)}). "
                    f"Watch the 31-60 bucket — that's the leading edge.")

    # SambaSafety — surface expiring licenses or MVR high-risk count.
    if samba:
        n_high = len(samba.get("high_risk") or [])
        lic_issues = samba.get("license_issues") or []
        soon = [d for d in lic_issues
                if isinstance(d.get("days_to_exp"), int)
                and 0 <= d["days_to_exp"] <= 30]
        bits = []
        if soon:
            bits.append(f"{len(soon)} license"
                        f"{'s' if len(soon) != 1 else ''} expiring within 30d")
        if n_high:
            bits.append(f"{n_high} driver{'s' if n_high != 1 else ''} "
                        f"high-risk per MVR")
        if bits:
            parts.append("Driver compliance: " + " · ".join(bits) + " (pg 2).")

    if not parts:
        parts.append(f"{mtd_label} signal currently sparse — "
                     "see entity table and detail pages for the read.")
    return " ".join(parts)


# ----------------------------------------------------------------------
# Action items — auto-detected from threshold breaches
# ----------------------------------------------------------------------
def action_items(*, alvys: dict | None, qb_ar: dict | None,
                 alvys_ar: dict | None, samsara: dict | None,
                 rpm_goal: dict | None, uninvoiced: dict | None,
                 prior_snapshot: dict | None = None,
                 samba: dict | None = None,
                 max_items: int = 3) -> list[tuple[str, str, str]]:
    """Return up to `max_items` action cards, severity-sorted (bad first).
    Each tuple is (severity, title, body) where severity is 'bad' / 'warn'.

    If `prior_snapshot` is provided (from scorecard_snapshots.read_prior_snapshot),
    real trend labels like 'CLIMBING' / 'GROWING' surface only when the
    delta from the snapshot exceeds the configured threshold."""
    items: list[tuple[str, str, str]] = []
    prior = prior_snapshot or {}

    # 1. Top idler — almost always the highest-leverage coaching opportunity.
    idle = ((samsara or {}).get("fleet") or {}).get("idle") or []
    if idle:
        top = idle[0]
        idle_pct = top.get("idle_pct") or 0
        if idle_pct > 0.65:
            fuel_cost = (top.get("idle_hours", 0) * IDLE_GPH * DIESEL_PRICE)
            driver = top.get("driver") or "Unassigned"
            items.append((
                "bad",
                f"TOP IDLER · {driver.upper()}",
                f"Truck {top.get('unit', '—')} · {_pct(idle_pct)} idle. "
                f"~{_money(fuel_cost)}/mo of fuel burned parked. "
                f"See pg 6 for the full idle ranking and talk track."))

    # 2. RPM goal gap.
    if rpm_goal:
        actual = rpm_goal.get("actual_rpm")
        goal = rpm_goal.get("goal_rpm")
        if _isnum(actual) and _isnum(goal) and actual < goal:
            gap = goal - actual
            miles = (alvys or {}).get("mtd", {}).get("miles") or 0
            annual = gap * miles * 12 if miles else None
            body = f"${gap:.2f}/mi below ${goal:.2f} goal."
            if annual:
                body += f" Closing it ≈ {_money(annual)} annual uplift."
            items.append(("warn", "RPM BELOW GOAL", body))

    # 3. AR 31-60 bucket — leading indicator of write-off risk. If we have
    # a prior snapshot AND today's value is materially higher, fire the
    # 'CLIMBING' card; otherwise fall back to a descriptive 'BUCKET' card
    # only when the bucket is materially large vs total 31+.
    if qb_ar:
        totals = qb_ar.get("totals") or {}
        v_31_60 = totals.get("31&ndash;60") or totals.get("31-60") or 0
        total_31_plus = qb_ar.get("total31") or 0
        share = (v_31_60 / total_31_plus) if total_31_plus else 0
        prior_31_60 = prior.get("qb_ar_31_60")
        if (_isnum(prior_31_60) and prior_31_60 > 0
                and v_31_60 > prior_31_60 * 1.20 and v_31_60 > 5000):
            delta = v_31_60 - prior_31_60
            since = f" since {prior.get('date', 'last snapshot')}"
            items.append((
                "warn",
                "AR 31-60 CLIMBING",
                f"{_money(v_31_60)} in 31-60 (+{_money(delta)}{since}). "
                f"Collections call list on pg 7."))
        elif v_31_60 > 20000 or (v_31_60 > 10000 and share > 0.20):
            items.append((
                "warn",
                "AR 31-60 BUCKET",
                f"{_money(v_31_60)} in 31-60 ({_pct(share)} of 31+ total). "
                f"Collections call list on pg 7."))

    # 4. Un-invoiced loads (gap between Alvys revenue and QB invoicing).
    # Fire 'GROWING' label when count is up materially vs prior snapshot.
    if uninvoiced:
        n = uninvoiced.get("count") or 0
        amt = uninvoiced.get("total_revenue") or 0
        prior_n = prior.get("uninvoiced_count")
        prior_amt = prior.get("uninvoiced_amt")
        growing = (_isnum(prior_n) and prior_n > 0
                   and (n - prior_n) >= 3 and n >= 10)
        if growing:
            delta_n = int(n - prior_n)
            since = f" since {prior.get('date', 'last snapshot')}"
            items.append((
                "warn",
                "UN-INVOICED LOADS GROWING",
                f"{n} delivered Alvys loads not yet invoiced (+{delta_n}{since}). "
                f"{_money(amt)} total. See pg 8."))
        elif n >= 10 or amt > 50000:
            items.append((
                "warn",
                "UN-INVOICED LOADS",
                f"{n} delivered Alvys loads not yet invoiced in QB "
                f"({_money(amt)}). See pg 8."))

    # 5. SambaSafety — expiring license is hard-deadline operational risk;
    # an expired CDL grounds the truck immediately. Surface as 'bad' if
    # anything is already expired or expires within 7 days, otherwise as
    # 'warn' for the 30-day horizon.
    if samba:
        lic_issues = samba.get("license_issues") or []
        expired = [d for d in lic_issues if d.get("expired")]
        soon_7 = [d for d in lic_issues
                  if isinstance(d.get("days_to_exp"), int)
                  and 0 <= d["days_to_exp"] <= 7]
        soon_30 = [d for d in lic_issues
                   if isinstance(d.get("days_to_exp"), int)
                   and 0 <= d["days_to_exp"] <= 30]
        if expired or soon_7:
            worst = (expired + soon_7)[0]
            days = worst.get("days_to_exp")
            when = ("EXPIRED" if (worst.get("expired") and
                                   (days is None or days < 0))
                    else f"expires in {int(days or 0)}d")
            items.append((
                "bad",
                f"CDL {when} · {str(worst.get('name', '')).upper()}",
                f"{len(expired)} expired + {len(soon_7)} expiring within 7d. "
                f"Pull driver off the board until renewed. See pg 2."))
        elif soon_30:
            items.append((
                "warn",
                "CDL RENEWALS UPCOMING",
                f"{len(soon_30)} driver{'s' if len(soon_30) != 1 else ''} "
                f"with license expiring within 30d. See pg 2."))
        n_high = len(samba.get("high_risk") or [])
        if n_high:
            items.append((
                "warn",
                f"MVR HIGH RISK · {n_high} DRIVER{'S' if n_high != 1 else ''}",
                f"Per latest SambaSafety MVR scan. See pg 2 for names."))

    # 6. Safety event — only surface if 24h count is non-zero.
    win24 = ((samsara or {}).get("windows") or {}).get("events") or {}
    e24 = win24.get("24h") if isinstance(win24, dict) else None
    if _isnum(e24) and e24 > 0:
        items.append((
            "warn",
            "SAFETY EVENT · 24h",
            f"{int(e24)} event{'s' if int(e24) != 1 else ''} in last 24h. "
            f"See pg 3 for detail."))

    # Severity-sort: bad first, then warn.
    items.sort(key=lambda x: 0 if x[0] == "bad" else 1)
    return items[:max_items]


# ----------------------------------------------------------------------
# Coaching cards — per-driver talk tracks
# ----------------------------------------------------------------------
def coaching_cards(*, samsara: dict | None,
                   max_cards: int = 3) -> list[tuple[str, str, str]]:
    """Return per-driver coaching cards as (name+truck, fact, talk_track)."""
    if not samsara:
        return []
    idle = (samsara.get("fleet") or {}).get("idle") or []
    cards: list[tuple[str, str, str]] = []
    fleet_mpg = (samsara.get("fleet") or {}).get("fleet_mpg")

    for r in idle[:max_cards]:
        idle_pct = r.get("idle_pct") or 0
        if idle_pct < 0.40:
            break   # don't surface drivers below the watch line
        driver = (r.get("driver") or "Unassigned").strip()
        truck = r.get("unit", "—")
        mpg = r.get("mpg")
        fuel = r.get("idle_hours", 0) * IDLE_GPH * DIESEL_PRICE

        # Threshold-keyed talk-track templates. Order matters — first match wins.
        talk = _pick_talk_track(idle_pct, mpg, fleet_mpg)

        fact_parts = [f"{_pct(idle_pct)} idle", f"{_money(fuel)} fuel"]
        if _isnum(mpg):
            fact_parts.append(f"{mpg:.2f} MPG")
        fact = " · ".join(fact_parts)

        name_line = f"{driver.upper()} · {truck}"
        cards.append((name_line, fact, talk))
    return cards


def _pick_talk_track(idle_pct: float, mpg: float | None,
                     fleet_mpg: float | None) -> str:
    """Pattern-match driver KPIs to one of the canned scripts."""
    is_low_mpg = (_isnum(mpg) and _isnum(fleet_mpg)
                  and mpg < fleet_mpg - 0.4)

    if idle_pct > 0.70 and is_low_mpg:
        return ('"High idle (' + _pct(idle_pct) + ') AND MPG below fleet '
                'average — usually means heavy AC use, long shipper waits, '
                'or both. Let\'s look at engine-off windows over 5 min '
                'and shipper delay reporting."')
    if idle_pct > 0.70:
        return ('"We\'re seeing ' + _pct(idle_pct) + ' idle time — about 3× '
                'fleet average. What\'s driving the long waits — shipper '
                'delays? Park time? Let\'s shut down anything over 5 '
                'minutes when stopped."')
    if idle_pct > 0.55 and is_low_mpg:
        return ('"Combination of high idle (' + _pct(idle_pct) + ') and low '
                'MPG (' + f"{mpg:.2f}" + ') is unusual. Let\'s check engine '
                'derate codes and your route timing."')
    if idle_pct > 0.55:
        return ('"Idle\'s eating into your check — every 10 hrs is ~$30 of '
                'fuel out of your pocket at current diesel prices. Let\'s '
                'plan APU use and stop-and-shutdown habits."')
    return ('"Idle time is creeping up to ' + _pct(idle_pct) + '. Quick check '
            '— anything different about your routes or shippers lately?"')


# ----------------------------------------------------------------------
# Per-page context strips — bridge from page 1's narrative to detail
# ----------------------------------------------------------------------
def page_strips(*, alvys: dict | None, qb_ar: dict | None,
                alvys_ar: dict | None, samsara: dict | None,
                uninvoiced: dict | None,
                samba: dict | None = None) -> dict[int, str]:
    """One short callout per detail page, keyed by page number."""
    out: dict[int, str] = {}

    # === SAFETY ===
    # Page 2 — SambaSafety (MVR + license)
    if samba and samba.get("monitored"):
        bits = [f"{int(samba['monitored'])} drivers monitored"]
        n_lic = len(samba.get("license_issues") or [])
        if n_lic:
            bits.append(f"{n_lic} license issue{'s' if n_lic != 1 else ''}")
        n_high = len(samba.get("high_risk") or [])
        if n_high:
            bits.append(f"{n_high} high-risk per MVR")
        n_viol = len(samba.get("violations") or [])
        if n_viol:
            bits.append(f"{n_viol} violation{'s' if n_viol != 1 else ''} in last "
                        f"{int(samba.get('window_days') or 365)}d")
        strip = " · ".join(bits) + "."
        ranked = samba.get("ranked") or []
        if ranked:
            worst = ranked[0]
            score = worst.get("score")
            if _isnum(score):
                strip += (f" Worst risk: {str(worst.get('name', '')).upper()} "
                          f"(score {score:.0f}).")
        out[2] = strip
    else:
        out[2] = ("SambaSafety MVR data not loaded this run &mdash; check "
                  "OneDrive/SambaSafety/ for the daily CSV drops.")

    # Page 3 — Safety Detail (Samsara events / HOS / DVIR / coaching)
    win24 = ((samsara or {}).get("windows") or {}).get("events") or {}
    e24 = win24.get("24h") if isinstance(win24, dict) else 0
    out[3] = (f"Page 1's safety summary captured {int(e24 or 0)} event"
              f"{'s' if int(e24 or 0) != 1 else ''} in last 24h. "
              f"Per-event detail and coaching status below.")

    # === OPERATIONAL ===
    # Page 4 — Driver Mileage
    mtd = (alvys or {}).get("mtd") or {}
    miles = mtd.get("miles")
    if _isnum(miles):
        out[4] = (f"Page 1's mileage tile shows {_num(miles)} miles "
                  f"period-to-date. Per-driver breakdown below.")

    # Page 5 — Fleet Operations (MPG / speeding)
    fleet = (samsara or {}).get("fleet") or {}
    fleet_mpg = fleet.get("fleet_mpg")
    if _isnum(fleet_mpg):
        out[5] = (f"Fleet MPG is running {fleet_mpg:.2f} (Samsara Trips). "
                  f"Best/worst trucks and speeders below; full idle ranking "
                  f"is on page 6.")

    # Page 6 — Fleet Idle (its own page)
    idle = fleet.get("idle") or []
    if idle:
        top = idle[0]
        out[6] = (f"Page 1's coaching cards came from this data. Worst idler: "
                  f"{(top.get('driver') or 'Unassigned').upper()} "
                  f"({top.get('unit', '—')}) at {_pct(top.get('idle_pct'))}. "
                  f"All trucks ranked worst-to-best by avg idle / week below.")

    # === ACCOUNTING ===
    # Page 7 — AR Overdue 31+
    if qb_ar:
        total31 = qb_ar.get("total31") or 0
        out[7] = (f"Page 1 flagged {_money(total31)} in 31+ AR. "
                  f"This is the collections call list. JW Logistics omitted "
                  f"per standing policy.")

    # Page 8 — Alvys un-invoiced + 90+ AR (combined)
    pg8_parts = []
    if uninvoiced:
        n = uninvoiced.get("count") or 0
        amt = uninvoiced.get("total_revenue") or 0
        pg8_parts.append(
            f"Page 1's QB-vs-Alvys gap mostly comes from these {n} "
            f"delivered-but-not-yet-invoiced loads ({_money(amt)}).")
    if alvys_ar:
        d91 = alvys_ar.get("d91plus") or 0
        if d91:
            pg8_parts.append(
                f"Below that, {_money(d91)} of 90+ AR — escalate to "
                f"collections.")
    if pg8_parts:
        out[8] = " ".join(pg8_parts)

    # Page 9 — QB↔Alvys recon
    out[9] = ("QB-vs-Alvys gap broken down per customer. Top rows = "
              "biggest contributors to the variance.")

    # Page 10 — Bill-by-bill match
    out[10] = ("Page 9 showed customer-level variances. This page drills to "
               "individual unmatched invoices.")

    return out
