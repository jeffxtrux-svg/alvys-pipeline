"""Unit tests for the dedicated-Operations-webhook routing in
src.teams_adaptive_cards.post_adaptive_cards.

Jackson + Dan's accountability card (equipment/DOT inspections, speeding,
prior-day logs, low safety score, high fuel cost/mile) can be routed to a
separate "Operations" Teams channel via TEAMS_OPERATIONS_WEBHOOK, instead of
sharing Audra's Safety & Compliance channel webhook. When unset, behavior is
unchanged — both cards use the shared webhook exactly as before.

Run directly:  python tests/test_teams_operations_routing.py
Or via pytest: pytest tests/test_teams_operations_routing.py
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.teams_adaptive_cards as tac  # noqa: E402

_ENV_KEYS = ["TEAMS_OPERATIONS_WEBHOOK", "TEAMS_PA_URL_AUDRA", "TEAMS_PA_URL_OPS",
            "TEAMS_PA_ONEDRIVE", "TEAMS_SAFETY_TEAM_ID", "TEAMS_SAFETY_CHANNEL_ID",
            "ONEDRIVE_USER_UPN"]


def _clear_env():
    for k in _ENV_KEYS:
        os.environ.pop(k, None)


def _acc_path() -> Path:
    acc = {
        "date": "2026-06-29",
        "audra": [{"category": "HOS Violation", "severity": "high",
                   "driver": "Audra Driver", "unit": None,
                   "detail": "x", "prompt": "y"}],
        "ops": [{"category": "High Fuel Cost / Mile", "severity": "medium",
                "driver": "Gary Abla", "unit": "44202",
                "detail": "x", "prompt": "y"}],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(acc, f)
        return Path(f.name)


def _label_of(payload: dict) -> str:
    return payload["attachments"][0]["content"]["body"][0]["items"][0]["text"]


def _install_fake_requests(calls: list):
    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        class _Resp:
            status_code = 200
            text = "ok"
        return _Resp()
    tac._requests = types.SimpleNamespace(post=fake_post)


def test_unset_operations_webhook_both_cards_use_shared_webhook():
    _clear_env()
    calls: list = []
    _install_fake_requests(calls)
    tac.post_adaptive_cards(_acc_path(), "https://shared.webhook/safety")
    assert len(calls) == 2
    urls = {url for url, _ in calls}
    assert urls == {"https://shared.webhook/safety"}   # both on the shared webhook


def test_set_operations_webhook_jackson_dan_routes_there_only():
    _clear_env()
    os.environ["TEAMS_OPERATIONS_WEBHOOK"] = "https://new.webhook/operations"
    calls: list = []
    _install_fake_requests(calls)
    tac.post_adaptive_cards(_acc_path(), "https://shared.webhook/safety")
    assert len(calls) == 2
    by_label = {_label_of(payload): url for url, payload in calls}
    assert by_label["📋 AUDRA — Safety Accountability"] == "https://shared.webhook/safety"
    assert by_label["📋 JACKSON + DAN — Safety Accountability"] == "https://new.webhook/operations"


def test_operations_webhook_bypasses_pa_and_graph():
    # Even if PA/Graph env vars are ALSO configured, the dedicated webhook
    # must win for Jackson+Dan — it's authoritative, not just another
    # fallback tier behind methods the user didn't choose.
    _clear_env()
    os.environ["TEAMS_OPERATIONS_WEBHOOK"] = "https://new.webhook/operations"
    os.environ["TEAMS_PA_URL_OPS"] = "https://pa.example/ops-flow"
    pa_calls: list = []

    def fake_pa(url, card):
        pa_calls.append(url)
        return True
    tac._post_card_pa = fake_pa

    calls: list = []
    _install_fake_requests(calls)
    tac.post_adaptive_cards(_acc_path(), "https://shared.webhook/safety")

    assert pa_calls == []   # PA HTTP trigger never invoked for ops
    by_label = {_label_of(payload): url for url, payload in calls}
    assert by_label["📋 JACKSON + DAN — Safety Accountability"] == "https://new.webhook/operations"


def test_audra_card_unaffected_by_operations_webhook():
    _clear_env()
    os.environ["TEAMS_OPERATIONS_WEBHOOK"] = "https://new.webhook/operations"
    calls: list = []
    _install_fake_requests(calls)
    tac.post_adaptive_cards(_acc_path(), "https://shared.webhook/safety")
    by_label = {_label_of(payload): url for url, payload in calls}
    assert by_label["📋 AUDRA — Safety Accountability"] == "https://shared.webhook/safety"


def test_no_ops_items_no_ops_post_even_with_dedicated_webhook():
    _clear_env()
    os.environ["TEAMS_OPERATIONS_WEBHOOK"] = "https://new.webhook/operations"
    acc = {"date": "2026-06-29",
           "audra": [{"category": "HOS Violation", "severity": "high",
                     "driver": "Audra Driver", "unit": None,
                     "detail": "x", "prompt": "y"}],
           "ops": []}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(acc, f)
        path = Path(f.name)
    calls: list = []
    _install_fake_requests(calls)
    tac.post_adaptive_cards(path, "https://shared.webhook/safety")
    assert len(calls) == 1   # only Audra posted


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
