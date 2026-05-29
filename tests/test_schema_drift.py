"""Tests for schema drift detection in transformers.find_drifted_paths.

Catches the case where Alvys renames a JSON field: the column_mappings.py
path silently stops resolving and the column goes blank in Excel. The drift
detector flags it the next run with the parent's sibling keys so the fix is
obvious.

Run directly:   python tests/test_schema_drift.py
Or via pytest:  pytest tests/test_schema_drift.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.transformers import find_drifted_paths, report_schema_drift  # noqa: E402


def _sample_records():
    return [
        {"LoadNumber": "L1", "Stops": [{"Address": {"City": "Dallas", "State": "TX"}}]},
        {"LoadNumber": "L2", "Stops": [{"Address": {"City": "Houston", "State": "TX"}}]},
        {"LoadNumber": "L3", "Stops": [{"Address": {"City": "Austin", "State": "TX"}}]},
    ]


def test_no_drift_when_all_paths_resolve():
    mappings = [
        ("Load #", "LoadNumber"),
        ("Origin City", "Stops.first.Address.City"),
    ]
    assert find_drifted_paths(_sample_records(), mappings) == []


def test_drift_detected_when_leaf_key_renamed():
    """Simulates Alvys renaming Address.City -> Address.CityName."""
    mappings = [("Origin City", "Stops.first.Address.City")]
    records = [
        {"Stops": [{"Address": {"CityName": "Dallas", "State": "TX"}}]},
        {"Stops": [{"Address": {"CityName": "Houston", "State": "TX"}}]},
    ]
    drifts = find_drifted_paths(records, mappings)
    assert len(drifts) == 1
    d = drifts[0]
    assert d["column"] == "Origin City"
    assert d["path"] == "Stops.first.Address.City"
    assert d["broken_at"] == "Stops.first.Address"
    assert d["missing_key"] == "City"
    assert "CityName" in d["siblings"]
    assert "State" in d["siblings"]


def test_drift_detected_when_intermediate_key_renamed():
    """Simulates Alvys renaming Address -> Location."""
    mappings = [("Origin City", "Stops.first.Address.City")]
    records = [
        {"Stops": [{"Location": {"City": "Dallas"}}]},
        {"Stops": [{"Location": {"City": "Houston"}}]},
    ]
    drifts = find_drifted_paths(records, mappings)
    assert len(drifts) == 1
    assert drifts[0]["missing_key"] == "Address"
    assert "Location" in drifts[0]["siblings"]


def test_one_resolving_record_clears_drift():
    """If at least one record resolves the path, it is NOT drift — assume
    transient missing data on the other records."""
    mappings = [("Origin City", "Stops.first.Address.City")]
    records = [
        {"Stops": [{"Address": {"CityName": "Dallas"}}]},  # would drift alone
        {"Stops": [{"Address": {"City": "Houston"}}]},       # but this resolves
    ]
    assert find_drifted_paths(records, mappings) == []


def test_legitimate_empty_data_is_not_drift():
    """Entirely-empty Stops lists are empty data, not drift. The walker sees
    'empty_list', not 'key_missing'."""
    mappings = [("Origin City", "Stops.first.Address.City")]
    records = [{"Stops": []}, {"Stops": []}]
    assert find_drifted_paths(records, mappings) == []


def test_null_intermediate_is_not_drift():
    """An intermediate value of None is empty data, not drift."""
    mappings = [("Origin City", "Stops.first.Address.City")]
    records = [{"Stops": [{"Address": None}]}, {"Stops": [{"Address": None}]}]
    assert find_drifted_paths(records, mappings) == []


def test_callable_and_none_accessors_are_skipped():
    mappings = [
        ("Lane", lambda r: "X"),
        ("Placeholder", None),
        ("Load #", "LoadNumber"),
    ]
    assert find_drifted_paths(_sample_records(), mappings) == []


def test_case_insensitive_keys_do_not_trigger_drift():
    """The path resolver is case-insensitive, so casing differences should
    not look like drift."""
    mappings = [("Origin City", "Stops.first.Address.City")]
    records = [{"Stops": [{"address": {"city": "Dallas"}}]}]
    assert find_drifted_paths(records, mappings) == []


def test_top_level_drift():
    """Drift at the very first path component."""
    mappings = [("Load #", "LoadNumber")]
    records = [{"LoadId": "L1", "Customer": "X"}, {"LoadId": "L2", "Customer": "Y"}]
    drifts = find_drifted_paths(records, mappings)
    assert len(drifts) == 1
    assert drifts[0]["broken_at"] == "(root)"
    assert drifts[0]["missing_key"] == "LoadNumber"
    assert "LoadId" in drifts[0]["siblings"]


def test_empty_records_returns_empty():
    assert find_drifted_paths([], [("X", "a.b")]) == []


def test_report_schema_drift_returns_list_and_does_not_raise():
    """The reporter wraps find_drifted_paths with logging — confirm it's a
    drop-in addition that returns the same list."""
    mappings = [("Origin City", "Stops.first.Address.City")]
    records = [{"Stops": [{"Address": {"CityName": "Dallas"}}]}]
    drifts = report_schema_drift(records, mappings, "Loads")
    assert len(drifts) == 1
    assert drifts[0]["missing_key"] == "City"


if __name__ == "__main__":
    fns = {k: v for k, v in dict(globals()).items()
           if k.startswith("test_") and callable(v)}
    for name, fn in fns.items():
        fn()
        print(f"  ok  {name}")
    print(f"\n{len(fns)} tests passed")
