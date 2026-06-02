"""Tests for the SambaSafety REST API client + workbook assembly.

No real network — every test injects a fake client whose responses match
the shapes documented in the SambaSafety Postman collection. These pin
the parsing logic so a SambaSafety schema change is caught loudly here
rather than silently in production.

Run directly (only needs pandas + openpyxl):
    python tests/test_sambasafety_client.py
"""
import io
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sambasafety_client import SambaSafetyClient, SambaSafetyError  # noqa: E402
from src.sambasafety_main import assemble_workbook_from_api  # noqa: E402


# ---------------------------------------------------------------------------
# Fake client — never hits the wire.
# ---------------------------------------------------------------------------
class _FakeClient(SambaSafetyClient):
    def __init__(self, *, groups=None, people=None, licenses=None,
                 statuses=None, mvr_lists=None, mvr_reports=None):
        self.base_url = "https://api-demo.sambasafety.io"
        self.timeout = 30
        self._headers = {"X-Api-Key": "fake", "Accept": "application/json"}
        self._groups = groups or []
        self._people = people or {}
        self._licenses = licenses or {}
        self._statuses = statuses or {}
        self._mvr_lists = mvr_lists or {}
        self._mvr_reports = mvr_reports or {}

    def list_groups(self):
        return self._groups

    def list_people_in_group(self, group_id):
        return self._people.get(group_id, [])

    def list_licenses_for_person(self, person_id):
        return self._licenses.get(person_id, [])

    def get_license_status(self, license_id):
        return self._statuses.get(license_id)

    def list_mvrs_for_person(self, person_id):
        return self._mvr_lists.get(person_id, [])

    def get_mvr_report(self, mvr_id):
        return self._mvr_reports.get(mvr_id)


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------
def test_client_requires_api_key():
    try:
        SambaSafetyClient("")
        raise AssertionError("expected SambaSafetyError for empty api_key")
    except SambaSafetyError:
        pass


def test_client_defaults_to_prod_base_url():
    c = SambaSafetyClient("fake-token")
    assert c.base_url == "https://api.sambasafety.io"
    assert c._headers["X-Api-Key"] == "fake-token"
    assert c._headers["Accept"] == "application/json"


def test_client_accepts_custom_base_url_and_strips_trailing_slash():
    c = SambaSafetyClient("fake", base_url="https://api-demo.sambasafety.io/")
    assert c.base_url == "https://api-demo.sambasafety.io"


# ---------------------------------------------------------------------------
# Workbook assembly — happy path
# ---------------------------------------------------------------------------
def _fixture_full():
    """One group, two drivers (one CDL, one archived) — exercises the
    archive-skip + CDL preference + MVR parsing."""
    return _FakeClient(
        groups=[
            {"groupId": "g1", "groupName": "X-Trux Drivers"},
            {"groupId": "g2", "groupName": "Other Team"},
        ],
        people={
            "g1": [
                {"personId": "p1", "firstName": "Bob", "lastName": "Trucker",
                 "archiveStatus": False},
                {"personId": "p2", "firstName": "Ex", "lastName": "Employee",
                 "archiveStatus": True},
            ],
            "g2": [
                {"personId": "p3", "firstName": "Other", "lastName": "Group",
                 "archiveStatus": False},
            ],
        },
        licenses={
            "p1": [
                {"licenseId": "L1", "licenseNumber": "IL12345",
                 "licenseState": "IL", "CDL": True},
            ],
            "p3": [
                {"licenseId": "L3", "licenseNumber": "TX99999",
                 "licenseState": "TX", "CDL": True},
            ],
        },
        statuses={
            "L1": {"licenseId": "L1", "status": "VALID",
                   "sourceDate": "2026-05-15T00:00:00Z"},
            "L3": {"licenseId": "L3", "status": "SUSPENDED",
                   "sourceDate": "2026-05-29T00:00:00Z"},
        },
        mvr_lists={
            "p1": [
                {"mvrId": "M1", "mvrDateTime": "2026-05-20T12:00:00Z"},
                {"mvrId": "M0", "mvrDateTime": "2024-01-01T00:00:00Z"},
            ],
            "p3": [
                {"mvrId": "M3", "mvrDateTime": "2026-04-01T00:00:00Z"},
            ],
        },
        mvr_reports={
            "M1": {
                "mvrId": "M1",
                "licenseExpirationDate": "2027-08-15",
                "riskScore": 22.0,
                "riskCategory": "Exception",
                "violations": [
                    {"violationDate": "2025-06-01",
                     "violationDescription": "Speeding 15+ over",
                     "violationScore": 8, "state": "IL",
                     "severity": "Major"},
                ],
            },
            "M0": {
                # Older MVR: only contributes violations, not expiration/risk.
                "mvrId": "M0",
                "violations": [
                    {"violationDate": "2023-09-09",
                     "violationDescription": "Failure to yield",
                     "violationScore": 3, "state": "IL",
                     "severity": "Minor"},
                ],
            },
            "M3": {
                "mvrId": "M3",
                "licenseExpirationDate": "2028-01-01",
                "riskScore": 5.0,
                "riskCategory": "Clean",
                "violations": [],
            },
        },
    )


def _read_workbook(xlsx_bytes):
    return pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name=None, engine="openpyxl")


def test_assemble_includes_active_drivers_and_skips_archived():
    sheets = _read_workbook(assemble_workbook_from_api(_fixture_full()))
    drivers = sheets["Drivers"]
    names = set(drivers["Driver Name"].tolist())
    assert "Bob Trucker" in names
    assert "Other Group" in names
    assert "Ex Employee" not in names      # archived → skipped


def test_assemble_can_filter_by_group_name_substring():
    sheets = _read_workbook(
        assemble_workbook_from_api(_fixture_full(), group_name_filter="X-Trux"))
    drivers = sheets["Drivers"]
    assert drivers["Driver Name"].tolist() == ["Bob Trucker"]


def test_assemble_pulls_license_metadata_and_status():
    sheets = _read_workbook(assemble_workbook_from_api(_fixture_full()))
    drivers = sheets["Drivers"].set_index("Driver Name")
    bob = drivers.loc["Bob Trucker"]
    assert bob["License Number"] == "IL12345"
    assert bob["License State"] == "IL"
    assert bob["License Status"] == "VALID"


def test_assemble_pulls_expiration_and_risk_from_latest_mvr():
    sheets = _read_workbook(assemble_workbook_from_api(_fixture_full()))
    drivers = sheets["Drivers"].set_index("Driver Name")
    # Expiration / Risk come from the *most recent* MVR (M1), not the older one (M0).
    assert pd.Timestamp(drivers.loc["Bob Trucker", "License Expiration"]) \
        == pd.Timestamp("2027-08-15")
    assert drivers.loc["Bob Trucker", "Risk Score"] == 22.0
    assert drivers.loc["Bob Trucker", "Risk Category"] == "Exception"


def test_assemble_collects_violations_across_all_mvrs():
    sheets = _read_workbook(assemble_workbook_from_api(_fixture_full()))
    violations = sheets["Violations"]
    bob_v = violations[violations["Driver Name"] == "Bob Trucker"]
    # Both MVRs contributed: M1 (Speeding 2025) + M0 (Failure to yield 2023).
    assert len(bob_v) == 2
    types = set(bob_v["Type"].tolist())
    assert "Speeding 15+ over" in types
    assert "Failure to yield" in types


def test_assemble_tolerates_missing_optional_fields():
    """A driver with no licenses and no MVRs should still land on the
    Drivers sheet with empty cells, not raise."""
    client = _FakeClient(
        groups=[{"groupId": "g1", "groupName": "X-Trux"}],
        people={"g1": [{"personId": "p1", "firstName": "Lone",
                        "lastName": "Wolf", "archiveStatus": False}]},
        licenses={}, statuses={}, mvr_lists={}, mvr_reports={},
    )
    sheets = _read_workbook(assemble_workbook_from_api(client))
    drivers = sheets["Drivers"]
    assert drivers["Driver Name"].tolist() == ["Lone Wolf"]
    assert drivers["License Status"].iloc[0] == "Unknown"


# ---------------------------------------------------------------------------
# Test runner
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
        except Exception as exc:
            failed += 1
            print(f"ERROR {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
