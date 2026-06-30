"""Unit tests for the fuel-coaching wiring in
src.safety_compliance_email._build_accountability_structured.

High-fuel-cost-per-mile drivers (from src.fuel_analytics.compute_fuel())
become ops-only Teams accountability items, reusing the existing
suppression/persistence registry — no new plumbing. These tests cover only
the fuel-specific wiring; the rest of _build_accountability_structured's
many item categories (HOS, DVIR, equipment, etc.) are exercised by running
the module directly, per this repo's existing testing convention.

Run directly:  python tests/test_safety_accountability_fuel.py
Or via pytest: pytest tests/test_safety_accountability_fuel.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.safety_compliance_email import _build_accountability_structured  # noqa: E402

_FUEL = {
    "fuel_cost_per_mile": 0.41,
    "high_cost_threshold": 0.55,
    "high_cost_drivers": [
        {"driver": "Gary Abla", "truck": "44202", "cost_per_mile": 0.68,
         "spend": 612.0, "gallons": 118.0},
        {"driver": "Hot Driver", "truck": "1", "cost_per_mile": 0.99,
         "spend": 900.0, "gallons": 150.0},
    ],
}


def test_no_fuel_arg_is_backward_compatible():
    # Existing callers / call signature without fuel= must still work unchanged.
    audra, ops = _build_accountability_structured({}, None, None, None)
    assert audra == [] and ops == []


def test_fuel_none_produces_no_items():
    audra, ops = _build_accountability_structured({}, None, None, None, fuel=None)
    assert ops == []


def test_fuel_with_no_high_cost_drivers_produces_no_items():
    audra, ops = _build_accountability_structured(
        {}, None, None, None, fuel={"high_cost_drivers": []})
    assert ops == []


def test_high_cost_drivers_become_ops_only_items():
    audra, ops = _build_accountability_structured({}, None, None, None, fuel=_FUEL)
    assert audra == []                        # fuel coaching is ops-only (Jackson + Dan)
    assert len(ops) == 2
    assert {i["driver"] for i in ops} == {"Gary Abla", "Hot Driver"}


def test_item_shape_matches_other_categories():
    audra, ops = _build_accountability_structured({}, None, None, None, fuel=_FUEL)
    item = next(i for i in ops if i["driver"] == "Gary Abla")
    assert item["category"] == "High Fuel Cost / Mile"
    assert item["severity"] == "medium"
    assert item["unit"] == "44202"
    assert "0.68" in item["detail"] and "0.55" in item["detail"]
    assert "612" in item["detail"] and "118" in item["detail"]
    assert item["prompt"]   # talk track present and non-empty


def test_severe_overage_driver_gets_distinct_talk_track():
    audra, ops = _build_accountability_structured({}, None, None, None, fuel=_FUEL)
    moderate = next(i for i in ops if i["driver"] == "Gary Abla")["prompt"]
    severe = next(i for i in ops if i["driver"] == "Hot Driver")["prompt"]
    assert moderate != severe


def test_driver_with_no_cost_per_mile_is_skipped():
    fuel = {"high_cost_threshold": 0.55,
            "high_cost_drivers": [{"driver": "No Miles Driver", "truck": "2",
                                   "cost_per_mile": None, "spend": 500.0, "gallons": 90.0}]}
    audra, ops = _build_accountability_structured({}, None, None, None, fuel=fuel)
    assert ops == []


def test_fuel_items_coexist_with_other_categories():
    # Speeding (an existing ops-only category) must still fire alongside fuel.
    samsara = {"fleet": {"scores_all": [{"driver": "Speedy", "speed_pct_7d": 5.0}]}}
    audra, ops = _build_accountability_structured({}, samsara, None, None, fuel=_FUEL)
    categories = {i["category"] for i in ops}
    assert "Speeding" in categories
    assert "High Fuel Cost / Mile" in categories


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
