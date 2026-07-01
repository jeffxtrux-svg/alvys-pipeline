"""Unit tests for the appointment scheduling logic in src/xfreight_etas.py.

Covers _stop_appt_iso, _stop_window_begin_iso, _fmt_appt_cell, and _fmt_delta —
the four functions that determine what deadline is used for delta calculation and
how the Appt column is displayed.

Run directly:  python tests/test_xfreight_etas.py
Or via pytest: pytest tests/test_xfreight_etas.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.xfreight_etas import (  # noqa: E402
    _stop_appt_iso, _stop_window_begin_iso, _fmt_appt_cell, _fmt_delta,
    _is_appt_stale, _fmt_appt_age, _STALE_APPT_HOURS,
    _norm_name, _name_keys, _build_hos_index, _hos_remaining,
    _is_date_only_window, _stop_date_only_iso,
    _locations_by_truck_name, _lookup_truck_gps,
)

# ---------------------------------------------------------------------------
# Fixtures — representative Alvys stop dicts
# ---------------------------------------------------------------------------
_APPT_TIME = "2026-06-24T13:00:00+00:00"
_WIN_BEGIN  = "2026-06-24T13:00:00+00:00"
_WIN_END    = "2026-06-24T17:00:00+00:00"

_STOP_APPT = {
    "ScheduleType": "APPT",
    "AppointmentDate": _APPT_TIME,
    "StopWindow": {},
}
_STOP_WINDOW = {
    "ScheduleType": "WINDOW",
    "AppointmentDate": None,
    "StopWindow": {"Begin": _WIN_BEGIN, "End": _WIN_END},
}
_STOP_FCFS_WITH_END = {
    "ScheduleType": "FCFS",
    "AppointmentDate": None,
    "StopWindow": {"Begin": _WIN_BEGIN, "End": _WIN_END},
}
_STOP_FCFS_OPEN = {
    "ScheduleType": "FCFS",
    "AppointmentDate": None,
    "StopWindow": {"Begin": _WIN_BEGIN},   # no End — open-ended FCFS
}
_STOP_FCFS_NONE = {
    "ScheduleType": "FCFS",
    "AppointmentDate": None,
    "StopWindow": {},
}


# ---------------------------------------------------------------------------
# _stop_appt_iso — deadline used for delta (ETA vs. this time)
# ---------------------------------------------------------------------------
def test_appt_stop_returns_appointment_date():
    assert _stop_appt_iso(_STOP_APPT) == _APPT_TIME


def test_window_stop_returns_end_not_begin():
    # Truck is only late when it MISSES the window close, not the window open.
    result = _stop_appt_iso(_STOP_WINDOW)
    assert result == _WIN_END
    assert result != _WIN_BEGIN


def test_fcfs_with_end_returns_end():
    assert _stop_appt_iso(_STOP_FCFS_WITH_END) == _WIN_END


def test_fcfs_open_ended_returns_none():
    # No hard deadline to compute a delta against.
    assert _stop_appt_iso(_STOP_FCFS_OPEN) is None


def test_fcfs_no_window_returns_none():
    assert _stop_appt_iso(_STOP_FCFS_NONE) is None


# ---------------------------------------------------------------------------
# _stop_window_begin_iso — display left-side of "Begin – End"
# ---------------------------------------------------------------------------
def test_appt_stop_window_begin_returns_none():
    # APPT stops show a single fixed time, not a range.
    assert _stop_window_begin_iso(_STOP_APPT) is None


def test_window_stop_returns_begin_when_end_present():
    assert _stop_window_begin_iso(_STOP_WINDOW) == _WIN_BEGIN


def test_fcfs_open_ended_window_begin_returns_none():
    # Only return Begin when End also exists (avoids a dangling "Begin –" range).
    assert _stop_window_begin_iso(_STOP_FCFS_OPEN) is None


# ---------------------------------------------------------------------------
# _fmt_appt_cell — HTML display in the Appt column
# ---------------------------------------------------------------------------
def _make_row(stop: dict) -> dict:
    """Build the subset of a row dict that _fmt_appt_cell reads."""
    from src.xfreight_etas import _parse_iso, _stop_appt_iso, _stop_window_begin_iso
    stype = (stop.get("ScheduleType") or "").upper()
    win = stop.get("StopWindow") or {}
    return {
        "appt_dt": _parse_iso(_stop_appt_iso(stop)),
        "appt_window_begin_dt": _parse_iso(_stop_window_begin_iso(stop)),
        "appt_stype": stype,
        "_fcfs_open_dt": (
            _parse_iso(win.get("Begin"))
            if stype == "FCFS" and not win.get("End") and win.get("Begin")
            else None
        ),
    }


def test_fmt_appt_cell_appt_shows_single_time():
    cell = _fmt_appt_cell(_make_row(_STOP_APPT))
    assert "–" not in cell and "FCFS" not in cell and cell != "—"


def test_fmt_appt_cell_window_shows_range():
    cell = _fmt_appt_cell(_make_row(_STOP_WINDOW))
    assert "–" in cell     # shows "Begin – End"


def test_fmt_appt_cell_fcfs_with_end_shows_range():
    cell = _fmt_appt_cell(_make_row(_STOP_FCFS_WITH_END))
    assert "–" in cell


def test_fmt_appt_cell_fcfs_open_shows_fcfs_label():
    cell = _fmt_appt_cell(_make_row(_STOP_FCFS_OPEN))
    assert "FCFS" in cell and "–" not in cell


def test_fmt_appt_cell_fcfs_no_window_shows_dash():
    cell = _fmt_appt_cell(_make_row(_STOP_FCFS_NONE))
    assert cell == "—"


# ---------------------------------------------------------------------------
# _fmt_delta — (text, color) for the Delta column
# ---------------------------------------------------------------------------
def test_fmt_delta_none_returns_dash():
    txt, color = _fmt_delta(None)
    assert txt == "—"


def test_fmt_delta_45_plus_late_is_red():
    _, color = _fmt_delta(-45)
    assert color == "#c41e2a"   # RED


def test_fmt_delta_under_45_late_is_amber():
    _, color = _fmt_delta(-30)
    assert color == "#d97706"   # AMBER


def test_fmt_delta_within_30_early_is_green():
    _, color = _fmt_delta(20)
    assert color == "#16a34a"


def test_fmt_delta_more_than_30_early_is_ink():
    _, color = _fmt_delta(60)
    assert color == "#1a1a1a"   # INK


# ---------------------------------------------------------------------------
# _is_appt_stale — guard against already-delivered / un-rescheduled loads
# (the "153h late" card on a 6-day-old appointment)
# ---------------------------------------------------------------------------
_NOW = datetime(2026, 6, 28, 22, 26, tzinfo=timezone.utc)


def test_appt_six_days_old_is_stale():
    # The Truck 42187 case: appt window closed Jun 22, "now" is Jun 28.
    appt = datetime(2026, 6, 22, 15, 0, tzinfo=timezone.utc)
    assert _is_appt_stale(appt, _NOW) is True


def test_appt_today_is_not_stale():
    # A same-day appt a few hours back is a real live-late event, not stale.
    appt = _NOW - timedelta(hours=3)
    assert _is_appt_stale(appt, _NOW) is False


def test_appt_just_inside_window_is_not_stale():
    # Exactly at the threshold is not yet stale (strictly greater than).
    appt = _NOW - timedelta(hours=_STALE_APPT_HOURS)
    assert _is_appt_stale(appt, _NOW) is False


def test_appt_just_past_window_is_stale():
    appt = _NOW - timedelta(hours=_STALE_APPT_HOURS + 1)
    assert _is_appt_stale(appt, _NOW) is True


def test_appt_none_is_not_stale():
    assert _is_appt_stale(None, _NOW) is False


def test_future_appt_is_not_stale():
    assert _is_appt_stale(_NOW + timedelta(hours=5), _NOW) is False


# ---------------------------------------------------------------------------
# _fmt_appt_age — "how long ago" label for the stale flag
# ---------------------------------------------------------------------------
def test_fmt_appt_age_days():
    appt = datetime(2026, 6, 22, 15, 0, tzinfo=timezone.utc)   # ~6.3 days before _NOW
    assert _fmt_appt_age(appt, _NOW) == "6d ago"


def test_fmt_appt_age_hours():
    assert _fmt_appt_age(_NOW - timedelta(hours=18), _NOW) == "18h ago"


def test_fmt_appt_age_future_is_blank():
    assert _fmt_appt_age(_NOW + timedelta(hours=2), _NOW) == ""


def test_fmt_appt_age_none_is_blank():
    assert _fmt_appt_age(None, _NOW) == ""


# ---------------------------------------------------------------------------
# Driver-name matching for HOS — closes the ~40% "hos = —" gap seen in prod
# ---------------------------------------------------------------------------
def test_norm_name_strips_punctuation_and_suffix():
    assert _norm_name("John A. Smith Jr.") == "john a smith"
    assert _norm_name("  MICHAEL   HALL  ") == "michael hall"


def test_name_keys_full_then_first_last():
    assert _name_keys("John A Smith") == ["john a smith", "john smith"]
    assert _name_keys("Michael Hall") == ["michael hall"]   # no middle → one key


def _hos_rec(name, ms):
    return {"driver": {"name": name}, "clocks": {"drive": {"driveRemainingDurationMs": ms}}}


def test_hos_exact_match_after_normalization():
    idx = _build_hos_index([_hos_rec("MICHAEL HALL", 11 * 3600 * 1000)])
    # Alvys gives a differently-cased name → still matches.
    assert _hos_remaining(idx, "Michael Hall") == 11 * 3600


def test_hos_first_last_alias_matches_across_middle_name():
    # Samsara clock has a middle initial; Alvys load has none (or vice versa).
    idx = _build_hos_index([_hos_rec("John A Smith", 5 * 3600 * 1000)])
    assert _hos_remaining(idx, "John Smith") == 5 * 3600
    # And the reverse: clock without middle, Alvys with one.
    idx2 = _build_hos_index([_hos_rec("John Smith", 5 * 3600 * 1000)])
    assert _hos_remaining(idx2, "John A Smith") == 5 * 3600


def test_hos_ambiguous_first_last_not_matched():
    # Two distinct drivers share first+last → the alias is dropped, so a
    # middle-less query does NOT silently bind to the wrong HOS clock.
    idx = _build_hos_index([
        _hos_rec("John A Smith", 1000 * 1000),
        _hos_rec("John B Smith", 2000 * 1000),
    ])
    assert _hos_remaining(idx, "John Smith") is None
    # …but each exact full name still resolves.
    assert _hos_remaining(idx, "John A Smith") == 1000
    assert _hos_remaining(idx, "John B Smith") == 2000


def test_hos_no_last_name_only_fallback():
    # Last-name-only must never match (wrong clock is worse than none).
    idx = _build_hos_index([_hos_rec("Gary Abla", 4 * 3600 * 1000)])
    assert _hos_remaining(idx, "Steve Abla") is None


def test_hos_missing_driver_returns_none():
    idx = _build_hos_index([_hos_rec("Gary Abla", 1000)])
    assert _hos_remaining(idx, "Benjamin Young") is None
    assert _hos_remaining(idx, "") is None


# ---------------------------------------------------------------------------
# Date-only window handling — a date with no time carries no hard deadline
# (the begin==end==midnight FCFS pattern seen across many prod loads)
# ---------------------------------------------------------------------------
_MIDNIGHT = "2026-06-30T00:00:00-05:00"
_STOP_DATE_ONLY = {
    "ScheduleType": "FCFS",
    "AppointmentDate": None,
    "StopWindow": {"Begin": _MIDNIGHT, "End": _MIDNIGHT},
}


def test_is_date_only_window_true_for_equal_midnight():
    assert _is_date_only_window(_MIDNIGHT, _MIDNIGHT) is True


def test_is_date_only_window_false_for_real_range():
    assert _is_date_only_window(_WIN_BEGIN, _WIN_END) is False


def test_date_only_stop_has_no_deadline():
    # The fix: midnight date-only window → no deadline, so no false lateness.
    assert _stop_appt_iso(_STOP_DATE_ONLY) is None
    # …but the date is still available for display.
    assert _stop_date_only_iso(_STOP_DATE_ONLY) == _MIDNIGHT


def test_date_only_stop_no_degenerate_range():
    # Must NOT return a window-begin (would render '12:00am – 12:00am').
    assert _stop_window_begin_iso(_STOP_DATE_ONLY) is None


def test_fmt_appt_cell_date_only_shows_date_any_time():
    from src.xfreight_etas import _parse_iso
    row = {
        "appt_dt": _parse_iso(_stop_appt_iso(_STOP_DATE_ONLY)),          # None
        "appt_window_begin_dt": _parse_iso(_stop_window_begin_iso(_STOP_DATE_ONLY)),
        "appt_stype": "FCFS",
        "_fcfs_open_dt": None,
        "_date_only_dt": _parse_iso(_stop_date_only_iso(_STOP_DATE_ONLY)),
    }
    cell = _fmt_appt_cell(row)
    assert "any time" in cell and "–" not in cell and cell != "—"


def test_date_only_displays_in_stop_zone_not_central():
    # An Eastern (-04:00) date-only delivery for Jun 30 must show 'Jun 30',
    # not 'Jun 29' — converting midnight-Eastern to Central would flip the day.
    from src.xfreight_etas import _parse_iso
    eastern_midnight = "2026-06-30T00:00:00-04:00"
    stop = {"ScheduleType": "FCFS",
            "StopWindow": {"Begin": eastern_midnight, "End": eastern_midnight}}
    row = {"appt_dt": None, "appt_window_begin_dt": None, "appt_stype": "FCFS",
           "_fcfs_open_dt": None, "_date_only_dt": _parse_iso(_stop_date_only_iso(stop))}
    cell = _fmt_appt_cell(row)
    assert "Jun 30" in cell and "Jun 29" not in cell


def test_equal_nonmidnight_window_is_fixed_time_not_date_only():
    # Begin==End at a real time is a fixed appointment, not date-only.
    t = "2026-06-30T14:00:00-05:00"
    stop = {"ScheduleType": "WINDOW", "StopWindow": {"Begin": t, "End": t}}
    assert _is_date_only_window(t, t) is False
    assert _stop_appt_iso(stop) == t           # the fixed time is the deadline
    assert _stop_window_begin_iso(stop) is None  # not a range


# ---------------------------------------------------------------------------
# Truck GPS matching — digits-only alias closes prefix mismatches
# ---------------------------------------------------------------------------
def _loc(name, lat=40.0, lng=-90.0):
    return {"name": name, "location": {"latitude": lat, "longitude": lng,
                                        "time": "2026-06-28T22:00:00Z"}}


def test_truck_gps_exact_match():
    locs = _locations_by_truck_name([_loc("42187")])
    assert _lookup_truck_gps(locs, "42187") is not None


def test_truck_gps_digits_alias_matches_prefixed_name():
    locs = _locations_by_truck_name([_loc("Truck 42187")])
    assert _lookup_truck_gps(locs, "42187") is not None   # Alvys plain number


def test_truck_gps_ambiguous_digits_not_aliased():
    # Two vehicles resolving to the same digits → alias dropped (no wrong GPS).
    locs = _locations_by_truck_name([_loc("Truck 5", 1, 1), _loc("#5", 2, 2)])
    assert _lookup_truck_gps(locs, "5") is None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
