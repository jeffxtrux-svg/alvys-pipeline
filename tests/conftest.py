"""Pytest session configuration for alvys-pipeline tests.

RPM_GOAL_OVERHEAD_PIN=0.98 in production pins the live-computed overhead
to a hand-set value while the costing algorithm is being validated. Tests
exercise the live math, so the pin must be disabled. The __main__ blocks
in each test file do this for direct python runs; conftest.py does the
same for pytest.
"""
import os

os.environ["RPM_GOAL_OVERHEAD_PIN"] = "0"
