"""Unit tests for src.detention_alerts — the collect-detention Teams cards.

A stop with ArrivedAt set and no DepartedAt whose dwell crosses the 2h
free-time window fires ONE alert card to the Operations channel; when the
driver departs, ONE closeout card posts the billable detention. State in
detention_state.json dedupes across the every-15-min ETA runs.

Run directly:  python tests/test_detention_alerts.py
Or via pytest: pytest tests/test_detention_alerts.py
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.detention_alerts as da  # noqa: E402

NOW = datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)


def _load(load_no="1001", customer="ACME Foods", brokered=False, stops=None):
    return {
        "LoadNumber": load_no,
        "CustomerName": customer,
        "BrokerageStatus": "Brokered" if brokered else "",
        "CustomerSalesAgentId": "u1",
        "Stops": stops or [],
    }


def _stop(arrived_hours_ago=None, departed_hours_ago=None, stop_type="Delivery",
          company="Cold Storage KC", city="Kansas City", state="MO",
          appt_iso=None, schedule_type="APPT", window=None):
    # Default appt 15:00 UTC == the arrived_hours_ago=3 arrival → on time.
    s = {
        "StopType": stop_type,
        "CompanyName": company,
        "Address": {"City": city, "State": state},
        "ScheduleType": schedule_type,
        "AppointmentDate": appt_iso or "2026-07-01T15:00:00+00:00",
    }
    if window is not None:
        s["StopWindow"] = window
        s.pop("AppointmentDate", None)
    if arrived_hours_ago is not None:
        s["ArrivedAt"] = (NOW - timedelta(hours=arrived_hours_ago)).isoformat()
    if departed_hours_ago is not None:
        s["DepartedAt"] = (NOW - timedelta(hours=departed_hours_ago)).isoformat()
    return s


TRIPS = {"1001": {"LoadNumber": "1001",
                  "Truck": {"TruckNum": "44202"},
                  "Driver1": {"FullName": "Gary Abla"}}}
USERS = {"u1": "Jeff Hannahs"}


def _find(loads, now=NOW, free=120):
    return da.find_detention_stops(loads, TRIPS, None, None, USERS,
                                   now=now, free_time_min=free)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def test_detects_stop_past_two_hours():
    rows = _find([_load(stops=[_stop(arrived_hours_ago=3)])])
    assert len(rows) == 1
    r = rows[0]
    assert r["key"] == "1001#0"
    assert r["customer_name"] == "ACME Foods"
    assert r["driver_name"] == "Gary Abla"
    assert r["truck_name"] == "44202"
    assert r["sales_agent"] == "Jeff Hannahs"
    assert r["stop_type"] == "Delivery"
    assert r["dwell_min"] == 180
    assert r["detention_min"] == 60


def test_under_threshold_not_detected():
    rows = _find([_load(stops=[_stop(arrived_hours_ago=1.5)])])
    assert rows == []


def test_departed_stop_not_detected():
    rows = _find([_load(stops=[_stop(arrived_hours_ago=5, departed_hours_ago=1)])])
    assert rows == []


def test_stale_arrival_skipped():
    # Arrived 30h ago with no departure = dispatch never closed the stop out —
    # a data gap, not a live detention event.
    rows = _find([_load(stops=[_stop(arrived_hours_ago=30)])])
    assert rows == []


def test_late_to_appointment_voids_detention():
    # Appt 14:00 UTC, arrived 15:00 UTC (3h before NOW=18:00) → late arrival:
    # detention is void, no card no matter how long the driver sits.
    rows = _find([_load(stops=[_stop(arrived_hours_ago=3,
                                     appt_iso="2026-07-01T14:00:00+00:00")])])
    assert rows == []


def test_early_to_appointment_clock_starts_at_appt():
    # Arrived 15:00, appt 15:30 → clock starts 15:30. By NOW=18:00 the clock
    # has run 2h30m → 30m of detention; on-site display still shows 3h.
    rows = _find([_load(stops=[_stop(arrived_hours_ago=3,
                                     appt_iso="2026-07-01T15:30:00+00:00")])])
    assert len(rows) == 1
    r = rows[0]
    assert r["early_arrival"] is True
    assert r["dwell_min"] == 180
    assert r["detention_min"] == 30
    assert r["clock_start_dt"].hour == 15 and r["clock_start_dt"].minute == 30


def test_fcfs_inside_window_is_billable():
    # FCFS window 12:00–20:00, arrived 15:00 (inside) → good, card fires.
    win = {"Begin": "2026-07-01T12:00:00+00:00", "End": "2026-07-01T20:00:00+00:00"}
    rows = _find([_load(stops=[_stop(arrived_hours_ago=3, schedule_type="FCFS",
                                     window=win)])])
    assert len(rows) == 1
    assert rows[0]["detention_min"] == 60   # clock from arrival (after Begin)


def test_fcfs_after_window_end_voids_detention():
    # FCFS window closed 14:00, arrived 15:00 → late to the window, void.
    win = {"Begin": "2026-07-01T08:00:00+00:00", "End": "2026-07-01T14:00:00+00:00"}
    rows = _find([_load(stops=[_stop(arrived_hours_ago=3, schedule_type="FCFS",
                                     window=win)])])
    assert rows == []


def test_open_ended_fcfs_cannot_be_late():
    # FCFS with no End — dock is open, first come first served: never late.
    win = {"Begin": "2026-07-01T08:00:00+00:00"}
    rows = _find([_load(stops=[_stop(arrived_hours_ago=3, schedule_type="FCFS",
                                     window=win)])])
    assert len(rows) == 1


def test_multiple_stops_keyed_independently():
    stops = [_stop(arrived_hours_ago=6, departed_hours_ago=4, stop_type="Pickup"),
             _stop(arrived_hours_ago=3)]
    rows = _find([_load(stops=stops)])
    assert [r["key"] for r in rows] == ["1001#1"]


# ---------------------------------------------------------------------------
# Card content
# ---------------------------------------------------------------------------
def _card_text(card: dict) -> str:
    import json
    return json.dumps(card)


def test_alert_card_carries_collection_details():
    rows = _find([_load(stops=[_stop(arrived_hours_ago=3)])])
    card = da.build_detention_card(rows, 120)
    text = _card_text(card)
    for needle in ("Collect Detention", "ACME Foods", "Gary Abla", "44202",
                   "1001", "Cold Storage KC", "Kansas City", "Jeff Hannahs",
                   "3h 0m on site", "Detention so far", "1h 0m",
                   "Notified Customer", "Detention Billed"):
        assert needle in text, f"missing {needle!r} in alert card"


def test_broker_labeled_on_brokered_load():
    rows = _find([_load(brokered=True, stops=[_stop(arrived_hours_ago=3)])])
    facts = da._row_facts(rows[0])
    assert any(f["title"] == "Broker" for f in facts)
    assert not any(f["title"] == "Customer" for f in facts)


def test_closeout_card_shows_billable_time():
    row = {"load_no": "1001", "customer_name": "ACME Foods", "brokered": False,
           "truck_name": "44202", "driver_name": "Gary Abla",
           "sales_agent": "Jeff Hannahs", "stop_type": "Delivery",
           "facility": "Cold Storage KC", "city": "Kansas City",
           "stop_state": "MO", "appt_display": "x", "arrived_late": False,
           "arrived_dt": NOW - timedelta(hours=5),
           "departed_dt": NOW - timedelta(hours=1),
           "total_min": 240, "billable_min": 120}
    text = _card_text(da.build_closeout_card([row], 120))
    for needle in ("Ready to Bill", "Billable detention: 2h 0m",
                   "Total on site", "4h 0m", "ACME Foods", "Gary Abla"):
        assert needle in text, f"missing {needle!r} in closeout card"


# ---------------------------------------------------------------------------
# Sync — state dedupe, closeout, expiry
# ---------------------------------------------------------------------------
class _FakeState:
    """Monkeypatch harness: in-memory state + captured webhook posts."""

    def __init__(self, initial=None):
        self.state = initial or {}
        self.posts = []
        da._load_state = lambda tok, upn, folder: self.state
        da._save_state = self._save
        da.requests = types.SimpleNamespace(post=self._post)

    def _save(self, tok, upn, folder, state):
        self.state = state

    def _post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return types.SimpleNamespace(status_code=200, text="ok")


def _sync(fake, loads, now=NOW):
    da.sync_detention_alerts(
        "https://hook/ops", "tok", "user@x.com", "ETA",
        loads=loads, trips_by_load=TRIPS, users_by_id=USERS,
        now=now, free_time_min=120,
    )
    return fake


def test_sync_posts_once_then_stays_quiet():
    fake = _FakeState()
    loads = [_load(stops=[_stop(arrived_hours_ago=3)])]
    _sync(fake, loads)
    assert len(fake.posts) == 1
    assert "Collect Detention" in _card_text(fake.posts[0][1])
    assert "1001#0" in fake.state["alerted"]

    # Second run 15 min later, driver still there — no repeat card.
    loads2 = [_load(stops=[_stop(arrived_hours_ago=3.25)])]
    _sync(fake, loads2, now=NOW + timedelta(minutes=15))
    assert len(fake.posts) == 1


def test_sync_closeout_posts_billable_and_clears_state():
    fake = _FakeState(initial={"alerted": {"1001#0": {
        "load_no": "1001", "stop_idx": 0,
        "arrived": (NOW - timedelta(hours=5)).isoformat(),
        "customer_name": "ACME Foods", "brokered": False,
        "truck_name": "44202", "driver_name": "Gary Abla",
        "sales_agent": "Jeff Hannahs", "stop_type": "Delivery",
        "facility": "Cold Storage KC", "city": "Kansas City",
        "stop_state": "MO", "appt_display": "x", "arrived_late": False,
    }}})
    # Driver departed after 4h on site → 2h billable.
    loads = [_load(stops=[_stop(arrived_hours_ago=5, departed_hours_ago=1)])]
    _sync(fake, loads)
    assert len(fake.posts) == 1
    text = _card_text(fake.posts[0][1])
    assert "Ready to Bill" in text
    assert "Billable detention: 2h 0m" in text
    assert fake.state["alerted"] == {}


def test_sync_expires_vanished_load_without_posting():
    fake = _FakeState(initial={"alerted": {"9999#0": {
        "load_no": "9999", "stop_idx": 0, "arrived": NOW.isoformat(),
    }}})
    _sync(fake, [])   # load fell out of the 7d fetch window
    assert fake.posts == []
    assert fake.state["alerted"] == {}


def test_sync_batches_new_stops_into_one_card():
    fake = _FakeState()
    loads = [
        _load("1001", stops=[_stop(arrived_hours_ago=3)]),
        _load("1002", customer="Beta Logistics",
              stops=[_stop(arrived_hours_ago=4, company="Dock West")]),
    ]
    _sync(fake, loads)
    assert len(fake.posts) == 1
    text = _card_text(fake.posts[0][1])
    assert "ACME Foods" in text and "Beta Logistics" in text
    assert set(fake.state["alerted"]) == {"1001#0", "1002#0"}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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
