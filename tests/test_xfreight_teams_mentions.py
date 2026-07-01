"""Unit tests for the Teams @mention + escalation feature in
src/xfreight_etas.py — pings Dan/Jackson directly (not just a passive
channel post) when a load first goes late, and again if it's still late
past the escalation threshold without resolving.

Run directly:  python tests/test_xfreight_teams_mentions.py
Or via pytest: pytest tests/test_xfreight_teams_mentions.py
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.xfreight_etas as eta  # noqa: E402
from src.xfreight_etas import (  # noqa: E402
    _mention_block, _resolve_mention_users, _build_teams_card,
    _build_escalation_card, _sync_teams_webhook, _ESCALATION_THRESHOLD_MIN,
)

_NOW = datetime(2026, 6, 29, 18, 0, tzinfo=timezone.utc)
_DAN = {"id": "aad-dan-123", "name": "Dan Heeren"}
_JACKSON = {"id": "aad-jackson-456", "name": "Jackson Smith"}


def _late_row(load_no="1009160", truck="45210", delta_min=-98):
    return {
        "load_no": load_no, "truck_name": truck, "driver_name": "Bradly Miles",
        "consignee": "BVB Freight", "consignee_city": "Jackson", "consignee_state": "MI",
        "appt_dt": None, "appt_window_begin_dt": None, "_fcfs_open_dt": None,
        "eta_dt": _NOW, "delta_min": delta_min,
        "hos_remaining_s": 9000, "hos_delay": False,
        "customer_name": "BVB Freight", "broker": "", "sales_agent": "Dan Heeren",
    }


# ---------------------------------------------------------------------------
# _mention_block
# ---------------------------------------------------------------------------
def test_mention_block_empty_list_returns_none_and_no_entities():
    block, entities = _mention_block([])
    assert block is None and entities == []


def test_mention_block_single_user():
    block, entities = _mention_block([_DAN])
    assert "<at>Dan Heeren</at>" in block["text"]
    assert "needs a response" in block["text"]
    assert entities == [{"type": "mention", "text": "<at>Dan Heeren</at>",
                         "mentioned": {"id": "aad-dan-123", "name": "Dan Heeren"}}]


def test_mention_block_two_users():
    block, entities = _mention_block([_DAN, _JACKSON])
    assert "<at>Dan Heeren</at>" in block["text"] and "<at>Jackson Smith</at>" in block["text"]
    assert len(entities) == 2


# ---------------------------------------------------------------------------
# _resolve_mention_users
# ---------------------------------------------------------------------------
class _FakeGraphResp:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


def test_resolve_mention_users_success():
    def fake_get(url, headers=None, params=None, timeout=None):
        email = url.rsplit("/", 1)[-1]
        return _FakeGraphResp(200, {"id": f"aad-{email}", "displayName": email.split("@")[0].title()})
    eta.requests = types.SimpleNamespace(get=fake_get)
    result = eta._resolve_mention_users("tok", ["dan@xfreight.net"])
    assert result == [{"id": "aad-dan@xfreight.net", "name": "Dan"}]


def test_resolve_mention_users_skips_unresolvable_email():
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeGraphResp(404, text="not found")
    eta.requests = types.SimpleNamespace(get=fake_get)
    result = eta._resolve_mention_users("tok", ["ghost@xfreight.net"])
    assert result == []


def test_resolve_mention_users_skips_on_exception():
    def fake_get(url, headers=None, params=None, timeout=None):
        raise ConnectionError("network down")
    eta.requests = types.SimpleNamespace(get=fake_get)
    result = eta._resolve_mention_users("tok", ["dan@xfreight.net"])
    assert result == []


def test_resolve_mention_users_partial_success():
    def fake_get(url, headers=None, params=None, timeout=None):
        email = url.rsplit("/", 1)[-1]
        if email == "dan@xfreight.net":
            return _FakeGraphResp(200, {"id": "aad-dan", "displayName": "Dan Heeren"})
        return _FakeGraphResp(403, text="insufficient privileges")
    eta.requests = types.SimpleNamespace(get=fake_get)
    result = eta._resolve_mention_users("tok", ["dan@xfreight.net", "jackson@xfreight.net"])
    assert result == [{"id": "aad-dan", "name": "Dan Heeren"}]


def test_resolve_mention_users_skips_blank_emails():
    calls = []
    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        return _FakeGraphResp(200, {"id": "x", "displayName": "X"})
    eta.requests = types.SimpleNamespace(get=fake_get)
    eta._resolve_mention_users("tok", ["", "  ", "dan@xfreight.net"])
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# _build_teams_card — mention wiring
# ---------------------------------------------------------------------------
def test_build_teams_card_without_mentions_has_no_entities():
    card = _build_teams_card([_late_row()])
    assert "entities" not in card["msteams"]


def test_build_teams_card_with_mentions_includes_block_and_entities():
    card = _build_teams_card([_late_row()], [_DAN, _JACKSON])
    body_text = json.dumps(card["body"])
    assert "<at>Dan Heeren</at>" in body_text and "<at>Jackson Smith</at>" in body_text
    assert card["msteams"]["entities"] == [
        {"type": "mention", "text": "<at>Dan Heeren</at>",
         "mentioned": {"id": "aad-dan-123", "name": "Dan Heeren"}},
        {"type": "mention", "text": "<at>Jackson Smith</at>",
         "mentioned": {"id": "aad-jackson-456", "name": "Jackson Smith"}},
    ]


# ---------------------------------------------------------------------------
# _build_escalation_card
# ---------------------------------------------------------------------------
def test_escalation_card_structure_and_content():
    card = _build_escalation_card([_late_row(load_no="1009160", delta_min=-98)], [_DAN])
    body_text = json.dumps(card["body"])
    assert "STILL LATE" in body_text
    assert "1009160" in body_text
    assert "1h 38m late" in body_text
    assert "<at>Dan Heeren</at>" in body_text
    assert card["msteams"]["entities"]


def test_escalation_card_without_mentions_has_no_entities():
    card = _build_escalation_card([_late_row()])
    assert "entities" not in card["msteams"]


# ---------------------------------------------------------------------------
# _sync_teams_webhook — escalation + mention end-to-end
# ---------------------------------------------------------------------------
class _FakeSyncEnv:
    """Fakes the three requests verbs _sync_teams_webhook needs: GET/PUT
    eta_state.json (OneDrive) and POST to the Teams webhook."""
    def __init__(self, initial_state=None):
        self.state = initial_state
        self.put_calls: list[dict] = []
        self.posted: list[dict] = []

    def get(self, url, headers=None, timeout=None, params=None):
        if self.state is None:
            return _FakeGraphResp(404)
        return _FakeGraphResp(200, self.state)

    def put(self, url, headers=None, data=None, timeout=None):
        self.state = json.loads(data)
        self.put_calls.append(self.state)
        return _FakeGraphResp(200)

    def post(self, url, json=None, timeout=None):
        self.posted.append(json)
        return _FakeGraphResp(200)


def _card_titles(env: _FakeSyncEnv) -> list[str]:
    return [p["attachments"][0]["content"]["body"][0]["text"] for p in env.posted]


def test_new_late_load_stamps_first_seen_no_escalation_yet():
    env = _FakeSyncEnv(initial_state=None)
    eta.requests = types.SimpleNamespace(get=env.get, put=env.put, post=env.post)
    _sync_teams_webhook("https://wh", "tok", "upn", "ETA", [_late_row()], [_DAN])

    assert len(env.posted) == 1   # only the main "Drivers Running Late" card
    assert "Drivers Running Late" in _card_titles(env)[0]
    saved = env.put_calls[-1]
    assert "1009160" in saved["load_first_seen"]
    assert saved["escalated_load_nos"] == []


def test_load_past_threshold_triggers_escalation_once():
    # _sync_teams_webhook computes elapsed time against the REAL clock
    # (datetime.now(timezone.utc)), not the fixed _NOW fixture — anchor
    # old_seen to real "now" so the threshold-crossing math is exact,
    # not coincidentally-stale relative to whatever _NOW happens to be.
    old_seen = (datetime.now(timezone.utc) - timedelta(minutes=_ESCALATION_THRESHOLD_MIN + 5)).isoformat()
    prior_state = {
        "alerted_load_nos": ["1009160"],
        "alerted_appts": {"1009160": ""},
        "load_first_seen": {"1009160": old_seen},
        "escalated_load_nos": [],
        "last_alerted": old_seen,
    }
    env = _FakeSyncEnv(initial_state=prior_state)
    eta.requests = types.SimpleNamespace(get=env.get, put=env.put, post=env.post)
    # Same load, same appt (unchanged) -> main card should NOT re-post, but
    # escalation SHOULD fire since it's independent of the main-card change check.
    _sync_teams_webhook("https://wh", "tok", "upn", "ETA", [_late_row()], [_DAN])

    titles = _card_titles(env)
    assert len(titles) == 1
    assert "STILL LATE" in titles[0]
    saved = env.put_calls[-1]
    assert saved["escalated_load_nos"] == ["1009160"]


def test_already_escalated_load_not_escalated_twice():
    # _sync_teams_webhook computes elapsed time against the REAL clock
    # (datetime.now(timezone.utc)), not the fixed _NOW fixture — anchor
    # old_seen to real "now" so the threshold-crossing math is exact,
    # not coincidentally-stale relative to whatever _NOW happens to be.
    old_seen = (datetime.now(timezone.utc) - timedelta(minutes=_ESCALATION_THRESHOLD_MIN + 5)).isoformat()
    prior_state = {
        "alerted_load_nos": ["1009160"],
        "alerted_appts": {"1009160": ""},
        "load_first_seen": {"1009160": old_seen},
        "escalated_load_nos": ["1009160"],   # already escalated last run
        "last_alerted": old_seen,
    }
    env = _FakeSyncEnv(initial_state=prior_state)
    eta.requests = types.SimpleNamespace(get=env.get, put=env.put, post=env.post)
    _sync_teams_webhook("https://wh", "tok", "upn", "ETA", [_late_row()], [_DAN])

    assert env.posted == []   # nothing changed, already escalated -> no posts at all


def test_resolved_load_clears_first_seen_and_escalated():
    # _sync_teams_webhook computes elapsed time against the REAL clock
    # (datetime.now(timezone.utc)), not the fixed _NOW fixture — anchor
    # old_seen to real "now" so the threshold-crossing math is exact,
    # not coincidentally-stale relative to whatever _NOW happens to be.
    old_seen = (datetime.now(timezone.utc) - timedelta(minutes=_ESCALATION_THRESHOLD_MIN + 5)).isoformat()
    prior_state = {
        "alerted_load_nos": ["1009160"],
        "alerted_appts": {"1009160": ""},
        "load_first_seen": {"1009160": old_seen},
        "escalated_load_nos": ["1009160"],
        "last_alerted": old_seen,
    }
    env = _FakeSyncEnv(initial_state=prior_state)
    eta.requests = types.SimpleNamespace(get=env.get, put=env.put, post=env.post)
    _sync_teams_webhook("https://wh", "tok", "upn", "ETA", [], [_DAN])   # load resolved

    saved = env.put_calls[-1]
    assert saved["load_first_seen"] == {}
    assert saved["escalated_load_nos"] == []
    # Two cards post: the "resolved" card for load 1009160, THEN the all-clear
    # card (since curr_load_nos is now empty) — check the last one.
    titles = _card_titles(env)
    assert len(titles) == 2
    assert "Resolved" in titles[0]
    assert "All Loads Back On Schedule" in titles[-1]


def test_mentions_passed_through_to_main_card_post():
    env = _FakeSyncEnv(initial_state=None)
    eta.requests = types.SimpleNamespace(get=env.get, put=env.put, post=env.post)
    _sync_teams_webhook("https://wh", "tok", "upn", "ETA", [_late_row()], [_DAN, _JACKSON])

    posted_body = json.dumps(env.posted[0])
    assert "<at>Dan Heeren</at>" in posted_body and "<at>Jackson Smith</at>" in posted_body


def test_no_mention_users_still_posts_card_without_entities():
    env = _FakeSyncEnv(initial_state=None)
    eta.requests = types.SimpleNamespace(get=env.get, put=env.put, post=env.post)
    _sync_teams_webhook("https://wh", "tok", "upn", "ETA", [_late_row()], [])

    assert len(env.posted) == 1
    assert "entities" not in env.posted[0]["attachments"][0]["content"]["msteams"]


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
        except Exception as exc:
            failed += 1
            print(f"ERROR {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
