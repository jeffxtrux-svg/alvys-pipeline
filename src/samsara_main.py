"""
Entry point for the Samsara → Excel pipeline.

Run locally:
    python -m src.samsara_main

Reads SAMSARA_API_TOKEN from .env (local) or environment (GitHub Actions).
Writes output/samsara/Samsara_Master.xlsx with one sheet per data type.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.samsara_client import SamsaraClient

log = logging.getLogger("samsara_main")

# openpyxl rejects ASCII control chars (except tab/LF/CR) embedded in strings
_ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Strip illegal Excel characters from all string cells."""
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].apply(
            lambda v: _ILLEGAL_CHARS.sub("", v) if isinstance(v, str) else v
        )
    return df


# --- Samsara value normalizers ------------------------------------------------
# Samsara returns timestamps as either epoch-ms (e.g. createdAtMs) or ISO-8601
# strings. Downstream (the scorecard window filters) needs a parseable form.
def _ts_to_str(value) -> str | None:
    """Epoch-ms (int/numeric str) or ISO-8601 string → 'YYYY-MM-DD HH:MM:SS' UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            return datetime.datetime.utcfromtimestamp(int(value) / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except (ValueError, OverflowError, OSError):
            return None
    try:
        return datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def build_dvir_defects(raw_dvirs: list[dict]) -> pd.DataFrame:
    """One row per DVIR defect (unit, driver, defect, resolved flag, time).

    json_normalize leaves the nested ``defects[]`` array as an unusable list
    cell, so we explode it here — same field shape that samsara_alerts.py reads.
    Keeps both resolved and unresolved so the scorecard can filter on ``Resolved``.
    """
    # Debug: dump the first DVIR so the real field shape is visible in the artifact.
    if raw_dvirs:
        try:
            import json as _json
            debug_dir = os.environ.get("DEBUG_DIR", "output/samsara/_debug")
            os.makedirs(debug_dir, exist_ok=True)
            with open(os.path.join(debug_dir, "sample_dvir.json"), "w") as f:
                _json.dump(raw_dvirs[0], f, indent=2, default=str)
            log.info("  DVIR keys in first record: %s", list(raw_dvirs[0].keys()))
        except Exception as e:
            log.warning("  could not dump sample DVIR: %s", e)

    rows: list[dict] = []
    for dvir in raw_dvirs or []:
        # /fleet/dvirs/history nests defects under vehicleDefects / trailerDefects;
        # older shapes used a flat "defects" list.
        defects: list = []
        for key in ("vehicleDefects", "trailerDefects", "defects"):
            v = dvir.get(key)
            if isinstance(v, list):
                defects.extend(v)
        if not defects:
            continue
        # Trailer DVIRs nest the asset under "asset", tractor DVIRs under "vehicle".
        # Trailer DVIRs may have no driver. Try every documented path so neither
        # surfaces as a "nan" string in the scorecard.
        def _pick_named(*candidates):
            for c in candidates:
                node = dvir.get(c)
                if isinstance(node, dict):
                    nm = node.get("name") or node.get("id")
                    if nm:
                        return nm
            return None
        unit = (_pick_named("asset", "vehicle", "trailer")
                or dvir.get("assetName") or dvir.get("vehicleName") or dvir.get("trailerName"))
        # Production trailer DVIRs put the driver in authorSignature.signatoryUser.name,
        # not under driver/submittedBy/etc — check that first.
        auth_user = ((dvir.get("authorSignature") or {}).get("signatoryUser") or {})
        driver_name = (auth_user.get("name") or auth_user.get("id")
                       or _pick_named("driver", "submittedBy", "createdBy", "inspector", "user")
                       or dvir.get("driverName") or dvir.get("submittedByName") or dvir.get("createdByName"))
        # DVIR records from /fleet/dvirs/history use startTime (no createdAt*); defects
        # carry their own createdAtTime. Prefer the defect's, fall back to the DVIR's.
        dvir_time = (dvir.get("startTime") or dvir.get("createdAtTime")
                     or dvir.get("submittedAtTime") or dvir.get("completedAtTime")
                     or dvir.get("createdAtMs") or dvir.get("createdAt"))
        dvir_type = dvir.get("inspectionType") or dvir.get("dvirType") or dvir.get("type")
        for d in defects:
            if not isinstance(d, dict):
                continue
            resolved = d.get("isResolved", d.get("resolved", False))
            rows.append({
                "Reported": _ts_to_str(d.get("createdAtTime") or d.get("createdAtMs") or dvir_time),
                "Unit": unit,
                "Driver": driver_name,
                "Defect": d.get("comment") or d.get("defectType") or "unspecified defect",
                "Defect Type": d.get("defectType"),
                "Resolved": bool(resolved),
                "Mechanic Notes": d.get("mechanicNotes") or d.get("resolvedComment") or ((d.get("resolvedBy") or {}).get("name")),
                "DVIR Type": dvir_type,
            })
    return pd.DataFrame(rows)


# Coarse severity buckets keyed off behavior names (adjust as needed).
_HIGH_SEVERITY = (
    "forward collision", "collision warning", "crash", "harsh brake",
    "following distance", "no seat belt", "ran red", "lane departure",
    "distracted", "drowsy", "mobile usage", "rolling stop",
)
_MED_SEVERITY = ("speeding", "harsh accel", "harsh turn", "harsh corner")


def _safety_event_type(rec: dict) -> str | None:
    """Decode the behaviorLabels array into a clean comma-joined event type."""
    labels = rec.get("behaviorLabels")
    if labels is None:
        labels = rec.get("behaviors")
    names: list[str] = []
    if isinstance(labels, list):
        for b in labels:
            if isinstance(b, dict):
                name = b.get("name") or b.get("label") or b.get("type")
            elif isinstance(b, str):
                name = b
            else:
                name = None
            if name:
                names.append(str(name))
    elif isinstance(labels, str):
        names.append(labels)
    if names:
        return ", ".join(dict.fromkeys(names))  # dedupe, preserve order
    return rec.get("name") or rec.get("eventType")


def _severity_for(event_type: str | None) -> str | None:
    if not event_type:
        return None
    t = event_type.lower()
    if any(k in t for k in _HIGH_SEVERITY):
        return "High"
    if any(k in t for k in _MED_SEVERITY):
        return "Medium"
    return "Low"


# Class-8 sleeper trucks burn ~0.8 gal/hr at idle per DOE / EPA studies
# (engine-only — APU-equipped trucks are lower, heavy-AC trucks can be
# higher; this is a fleet-average heuristic). Used as a fallback when
# Samsara's OBD fuel-counter signal isn't returned for a vehicle, which
# is the case for XFreight's current Samsara plan / truck mix.
IDLE_FUEL_RATE_GPH = 0.8


def build_engine_idle(raw_engine_history: list[dict],
                      driver_by_vehicle_id: dict[str, str] | None = None,
                      now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Aggregate engineStates transitions into idle / running / off hours per vehicle,
    bucketed by **settlement week** (Wed 3 PM Chicago → next Wed 2:59 PM).

    Produces a per-vehicle row with:
      - per-week idle + engine hours (5 weeks: W1..W4 complete + Cur partial)
      - aggregate Idle / On / Off / Running / Engine totals across the window
      - Driver Name (from /fleet/vehicles staticAssignedDriver, if provided)

    Each transition is credited to whichever settlement week its start time
    falls in. Transitions older than the 5-week window are dropped.
    """
    chi = "America/Chicago"
    now = now or pd.Timestamp.now(tz=chi)
    if now.tzinfo is None:
        now = now.tz_localize(chi)
    # Wed=2 (Mon=0). Anchor each week at Wed 15:00 Chicago.
    days_since_wed = (now.weekday() - 2) % 7
    cur_start = (now - pd.Timedelta(days=days_since_wed)).normalize() + pd.Timedelta(hours=15)
    if cur_start > now:
        cur_start -= pd.Timedelta(weeks=1)
    starts = [cur_start - pd.Timedelta(weeks=k) for k in range(5)][::-1]  # oldest first
    window_start = starts[0]
    week_labels = ["W1", "W2", "W3", "W4", "Cur"]

    rows = []
    dmap = driver_by_vehicle_id or {}
    for rec in raw_engine_history or []:
        states = rec.get("engineStates") or []
        if not isinstance(states, list) or len(states) < 2:
            continue
        try:
            states = sorted(states, key=lambda s: s.get("time", ""))
        except Exception:
            pass
        # Parse the parallel fuel-consumed counter (cumulative gallons since
        # current ignition cycle; resets each time vehicle starts). Build a
        # sorted list of (timestamp_utc, gallons) for interpolation lookup.
        fuel_raw = rec.get("obdFuelGallonsConsumedSinceVehicleStarted") or []
        fuel_samples: list[tuple[pd.Timestamp, float]] = []
        for fs in fuel_raw:
            ft = pd.to_datetime(fs.get("time"), errors="coerce", utc=True)
            fv = fs.get("value")
            if pd.isna(ft) or fv is None:
                continue
            try:
                fuel_samples.append((ft, float(fv)))
            except (TypeError, ValueError):
                continue
        fuel_samples.sort(key=lambda x: x[0])

        def fuel_at(t: pd.Timestamp) -> float | None:
            """Linear-interpolate the cumulative-fuel reading at time t.
            Returns None if t is outside the sample range."""
            if not fuel_samples:
                return None
            if t <= fuel_samples[0][0]:
                return fuel_samples[0][1]
            if t >= fuel_samples[-1][0]:
                return fuel_samples[-1][1]
            # Binary search would be faster; linear is fine at this scale.
            for i in range(len(fuel_samples) - 1):
                t0, v0 = fuel_samples[i]
                t1, v1 = fuel_samples[i + 1]
                if t0 <= t <= t1:
                    span = (t1 - t0).total_seconds()
                    if span <= 0:
                        return v1
                    frac = (t - t0).total_seconds() / span
                    return v0 + frac * (v1 - v0)
            return None

        per_week = [{"Idle": 0.0, "On": 0.0, "Off": 0.0, "Running": 0.0,
                     "IdleGal": 0.0} for _ in range(5)]
        for i in range(len(states) - 1):
            t0 = pd.to_datetime(states[i].get("time"), errors="coerce", utc=True)
            t1 = pd.to_datetime(states[i + 1].get("time"), errors="coerce", utc=True)
            if pd.isna(t0) or pd.isna(t1):
                continue
            secs = (t1 - t0).total_seconds()
            if secs <= 0:
                continue
            t0_chi = t0.tz_convert(chi)
            if t0_chi < window_start:
                continue
            # Bucket: which of the 5 settlement weeks contains t0?
            idx = None
            for k in range(5):
                end = starts[k + 1] if k < 4 else (starts[4] + pd.Timedelta(weeks=1))
                if starts[k] <= t0_chi < end:
                    idx = k
                    break
            if idx is None:
                continue
            val = states[i].get("value") or ""
            key = val if val in per_week[idx] else ("On" if val else "Off")
            per_week[idx][key] += secs
            # Idle-only fuel: integrate the cumulative-gallons curve across
            # the idle interval. Skip if a counter reset (ignition cycle)
            # happened mid-interval — those become negative deltas.
            if key == "Idle":
                f0 = fuel_at(t0)
                f1 = fuel_at(t1)
                if f0 is not None and f1 is not None and f1 >= f0:
                    per_week[idx]["IdleGal"] += (f1 - f0)

        # Heuristic fallback: when the OBD fuel counter isn't returned for a
        # given vehicle/week, fall back to idle_hours * IDLE_FUEL_RATE_GPH.
        # Class-8 fleet-average idle burn (~0.8 gal/hr) so the Idle Gal column
        # always populates, even on trucks Samsara doesn't surface fuel
        # telemetry for.
        for k in range(5):
            if per_week[k]["IdleGal"] == 0 and per_week[k]["Idle"] > 0:
                per_week[k]["IdleGal"] = (per_week[k]["Idle"] / 3600) * IDLE_FUEL_RATE_GPH

        vid = rec.get("id")
        row = {
            "Vehicle ID": vid,
            "Vehicle Name": rec.get("name"),
            "Driver Name": dmap.get(str(vid)) if vid is not None else None,
        }
        for k, lab in enumerate(week_labels):
            pw = per_week[k]
            row[f"Idle_{lab}"] = round(pw["Idle"] / 3600, 2)
            row[f"Engine_{lab}"] = round((pw["Idle"] + pw["On"] + pw["Running"]) / 3600, 2)
            row[f"IdleGal_{lab}"] = round(pw["IdleGal"], 1)
        tot_idle = sum(per_week[k]["Idle"] for k in range(5))
        tot_on = sum(per_week[k]["On"] for k in range(5))
        tot_off = sum(per_week[k]["Off"] for k in range(5))
        tot_run = sum(per_week[k]["Running"] for k in range(5))
        tot_idle_gal = sum(per_week[k]["IdleGal"] for k in range(5))
        row["Idle Hours"] = round(tot_idle / 3600, 2)
        row["On Hours"] = round(tot_on / 3600, 2)
        row["Off Hours"] = round(tot_off / 3600, 2)
        row["Running Hours"] = round(tot_run / 3600, 2)
        row["Engine Hours"] = round((tot_idle + tot_on + tot_run) / 3600, 2)
        row["Idle Gallons"] = round(tot_idle_gal, 1)
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Idle Hours", ascending=False).reset_index(drop=True)
    return df


def _hos_violation_type(rec: dict) -> str | None:
    return (
        rec.get("violationType")
        or rec.get("type")
        or rec.get("hosViolationType")
        or rec.get("name")
        or (rec.get("violation") or {}).get("type")
    )


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        sys.exit(f"ERROR: required env var {key!r} not set. Check your .env file.")
    return val


def flatten(records: list[dict], label: str = "") -> pd.DataFrame:
    """Flatten nested JSON records into a DataFrame via json_normalize."""
    log = logging.getLogger("samsara_main")
    if not records:
        if label:
            log.info("  %s: no records", label)
        return pd.DataFrame()
    try:
        df = pd.json_normalize(records, max_level=4)
        if label:
            log.info("  %s: %d rows × %d cols", label, len(df), len(df.columns))
        return df
    except Exception as e:
        log.warning("json_normalize failed for %s (%s) — falling back to basic DataFrame", label, e)
        return pd.DataFrame(records)


def write_samsara_xlsx(sheets: dict[str, pd.DataFrame], output_path: Path) -> None:
    log = logging.getLogger("samsara_main")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Writing %s", output_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            if df.empty:
                log.warning("  %s: no data — writing placeholder sheet", sheet_name)
                df = pd.DataFrame({"(no data retrieved)": []})
            df = _sanitize_df(df)
            # Excel sheet names max 31 chars
            safe_name = sheet_name[:31]
            df.to_excel(writer, sheet_name=safe_name, index=False)
            log.info("  %s: %d rows × %d cols", safe_name, len(df), len(df.columns))

    log.info("Done: %s", output_path.resolve())


def main() -> int:
    setup_logging()
    load_dotenv()
    log = logging.getLogger("samsara_main")

    api_token = get_required("SAMSARA_API_TOKEN")
    output_dir = Path(os.environ.get("SAMSARA_OUTPUT_DIR", "output/samsara"))
    days_back = int(os.environ.get("SAMSARA_DAYS_BACK", "90"))
    # Safety/DVIR/HOS-violation history must cover the scorecard's "previous
    # 6 months" window, so default to ~190 days (independent of trips, which
    # are per-vehicle and costlier to pull far back).
    safety_days_back = int(os.environ.get("SAMSARA_SAFETY_DAYS_BACK", "190"))

    now = datetime.datetime.utcnow()
    start_long = now - datetime.timedelta(days=days_back)
    start_safety = now - datetime.timedelta(days=safety_days_back)
    start_hos = now - datetime.timedelta(days=30)

    log.info("Samsara → Excel pipeline starting")
    log.info("Trips window               : %s → now (%d days)", start_long.date(), days_back)
    log.info("Safety/DVIR/HOS-viol window: %s → now (%d days)", start_safety.date(), safety_days_back)
    log.info("HOS-logs window            : %s → now (30 days)", start_hos.date())
    log.info("Output dir                 : %s", output_dir.resolve())

    client = SamsaraClient(api_token)

    log.info("=" * 60)
    log.info("Step 1/9: Vehicles")
    log.info("=" * 60)
    raw_vehicles = client.fetch_vehicles()

    log.info("=" * 60)
    log.info("Step 2/9: Drivers")
    log.info("=" * 60)
    raw_drivers = client.fetch_drivers()

    log.info("=" * 60)
    log.info("Step 3/9: Vehicle Stats (odometer, fuel, engine state)")
    log.info("=" * 60)
    raw_stats = client.fetch_vehicle_stats()

    log.info("=" * 60)
    log.info("Step 4/9: Current Locations")
    log.info("=" * 60)
    raw_locations = client.fetch_locations()

    log.info("=" * 60)
    log.info("Step 5/9: Trips (%d days)", days_back)
    log.info("=" * 60)
    vehicle_ids = [v["id"] for v in raw_vehicles if "id" in v]
    raw_trips = client.fetch_trips(start_long, now, vehicle_ids)

    log.info("=" * 60)
    log.info("Step 6/10: Safety Events (%d days)", safety_days_back)
    log.info("=" * 60)
    raw_safety = client.fetch_safety_events(start_safety, now)

    log.info("=" * 60)
    log.info("Step 7/10: HOS Logs (30 days)")
    log.info("=" * 60)
    raw_hos = client.fetch_hos_logs(start_hos, now)

    log.info("=" * 60)
    log.info("Step 8/10: HOS Violations (%d days)", safety_days_back)
    log.info("=" * 60)
    raw_hos_viol = client.fetch_hos_violations(start_safety, now)

    log.info("=" * 60)
    log.info("Step 9/10: DVIRs (%d days)", safety_days_back)
    log.info("=" * 60)
    raw_dvirs = client.fetch_dvirs(start_safety, now)

    log.info("=" * 60)
    log.info("Step 10/12: Engine state history (idle time, 36 days = 5 settlement weeks)")
    log.info("=" * 60)
    raw_engine_history = client.fetch_engine_state_history(
        now - datetime.timedelta(days=36), now
    )

    log.info("=" * 60)
    log.info("Step 11/12: Driver safety scores (%d days)", safety_days_back)
    log.info("=" * 60)
    driver_ids = [d["id"] for d in raw_drivers if "id" in d]
    raw_driver_scores = client.fetch_driver_safety_scores(
        driver_ids, start_safety, now
    )

    # Second pull for the current month-to-date so the scorecard can show a
    # current-month speeding % alongside the 6-month figure.
    mtd_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    log.info("=" * 60)
    log.info("Step 11b/12: Driver safety scores — MTD (%s → now)", mtd_start.date())
    log.info("=" * 60)
    raw_driver_scores_mtd = client.fetch_driver_safety_scores(
        driver_ids, mtd_start, now
    )

    log.info("=" * 60)
    log.info("Step 12/13: Coaching sessions (past-due tracking)")
    log.info("=" * 60)
    raw_coaching = client.fetch_coaching_sessions()

    log.info("=" * 60)
    log.info("Step 13/13: Training assignments (past-due tracking)")
    log.info("=" * 60)
    raw_training = client.fetch_training_assignments()

    log.info("=" * 60)
    log.info("Step 12/13: IFTA (last 3 months, fallback MPG source)")
    log.info("=" * 60)
    # Note: /fleet/reports/fuel-energy/usage doesn't exist in Samsara's API
    # (404). MPG is now computed from Trips data in compute_samsara; IFTA
    # remains as a fallback.
    ifta_sheets: dict[str, pd.DataFrame] = {}
    for months_ago in range(3):
        target = (now.replace(day=1) - datetime.timedelta(days=months_ago * 28)).replace(day=1)
        raw_ifta = client.fetch_ifta(target.year, target.month)
        if raw_ifta:
            df_ifta = flatten(raw_ifta, f"IFTA {target.year}-{target.month:02d}")
            df_ifta.insert(0, "Period", f"{target.year}-{target.month:02d}")
            key = f"IFTA_{target.year}_{target.month:02d}"
            ifta_sheets[key] = df_ifta

    log.info("=" * 60)
    log.info("Flattening to DataFrames")
    log.info("=" * 60)

    # Safety events: add clean Event Type / Severity / Driver / Unit columns,
    # since behaviorLabels[] does not flatten into a usable column.
    df_safety = flatten(raw_safety, "SafetyEvents")
    if not df_safety.empty and len(df_safety) == len(raw_safety):
        event_types = [_safety_event_type(r) for r in raw_safety]
        df_safety["Event Type"] = event_types
        df_safety["Severity"] = [_severity_for(t) for t in event_types]
        df_safety["Driver Name"] = [(r.get("driver") or {}).get("name") for r in raw_safety]
        df_safety["Unit"] = [(r.get("vehicle") or {}).get("name") for r in raw_safety]

    # HOS violations: add clean Driver / Violation Type columns.
    df_hosv = flatten(raw_hos_viol, "HOS_Violations")
    if not df_hosv.empty and len(df_hosv) == len(raw_hos_viol):
        df_hosv["Driver Name"] = [(r.get("driver") or {}).get("name") for r in raw_hos_viol]
        df_hosv["Violation Type"] = [_hos_violation_type(r) for r in raw_hos_viol]
        # The /fleet/hos/violations record carries the violation timestamp under
        # ``violationStartTime`` — json_normalize doesn't always surface nested
        # fields as columns, so set it explicitly for the scorecard's date logic.
        df_hosv["violationStartTime"] = [r.get("violationStartTime") for r in raw_hos_viol]

    df_dvir_defects = build_dvir_defects(raw_dvirs)
    log.info("  DVIR_Defects: %d rows (exploded from %d DVIRs)",
             len(df_dvir_defects), len(raw_dvirs))

    # Build a vehicle_id -> assigned-driver-name map from /fleet/vehicles so
    # the EngineIdle sheet can call out who's been parked. Samsara puts the
    # current assignment under staticAssignedDriver{id,name}.
    driver_by_vehicle: dict[str, str] = {}
    for v in raw_vehicles or []:
        vid = v.get("id")
        d = v.get("staticAssignedDriver") or {}
        nm = d.get("name") if isinstance(d, dict) else None
        if vid is not None and nm:
            driver_by_vehicle[str(vid)] = nm
    df_idle = build_engine_idle(raw_engine_history, driver_by_vehicle)
    log.info("  EngineIdle: %d rows (aggregated from %d vehicles' state history, "
             "%d with assigned driver)",
             len(df_idle), len(raw_engine_history), len(driver_by_vehicle))

    df_driver_scores = flatten(raw_driver_scores, "DriverSafetyScores")
    df_driver_scores_mtd = flatten(raw_driver_scores_mtd, "DriverSafetyScoresMtd")
    # Stamp the driver name onto each row by joining with the drivers sheet.
    drivers_df = flatten(raw_drivers, "Drivers")
    name_by_id: dict = {}
    if not drivers_df.empty and "id" in drivers_df.columns and "name" in drivers_df.columns:
        name_by_id = dict(zip(drivers_df["id"].astype(str), drivers_df["name"]))
    for _df in (df_driver_scores, df_driver_scores_mtd):
        if not _df.empty and "driverId" in _df.columns and name_by_id:
            _df["Driver Name"] = _df["driverId"].astype(str).map(name_by_id)

    # Coaching sessions: extract flat columns the scorecard can use directly.
    def _build_coaching_df(records: list[dict]) -> pd.DataFrame:
        rows = []
        for r in records:
            drv = r.get("driver") or {}
            behaviors = r.get("behaviors") or []
            beh_str = ", ".join(
                b.get("behaviorId") or b.get("type") or str(b)
                for b in behaviors if isinstance(b, dict)
            )
            rows.append({
                "Driver Name":  drv.get("name") or drv.get("id") or "",
                "Driver ID":    drv.get("id") or "",
                "Type":         r.get("type") or "",          # selfCoaching / managerLed
                "Status":       r.get("status") or "",        # pending / completed / dismissed
                "Behaviors":    beh_str,
                "Assigned At":  r.get("assignedAt") or r.get("createdAt") or "",
                "Due At":       r.get("dueAt") or "",
                "Completed At": r.get("completedAt") or "",
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["Driver Name", "Driver ID", "Type", "Status",
                     "Behaviors", "Assigned At", "Due At", "Completed At"])

    # Training assignments: extract flat columns.
    def _build_training_df(records: list[dict]) -> pd.DataFrame:
        rows = []
        for r in records:
            drv = r.get("driver") or {}
            course = r.get("course") or {}
            rows.append({
                "Driver Name":    drv.get("name") or drv.get("id") or "",
                "Driver ID":      drv.get("id") or "",
                "Course":         course.get("name") or course.get("id") or "",
                "Status":         r.get("status") or "",
                "Assigned At":    r.get("assignedAt") or r.get("createdAt") or "",
                "Due At":         r.get("dueAt") or "",
                "Completed At":   r.get("completedAt") or "",
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["Driver Name", "Driver ID", "Course", "Status",
                     "Assigned At", "Due At", "Completed At"])

    df_coaching  = _build_coaching_df(raw_coaching)
    df_training  = _build_training_df(raw_training)
    log.info("  CoachingSessions: %d rows", len(df_coaching))
    log.info("  TrainingAssignments: %d rows", len(df_training))

    sheets: dict[str, pd.DataFrame] = {
        "Vehicles":       flatten(raw_vehicles,  "Vehicles"),
        "Drivers":        flatten(raw_drivers,   "Drivers"),
        "VehicleStats":   flatten(raw_stats,     "VehicleStats"),
        "Locations":      flatten(raw_locations, "Locations"),
        "Trips":          flatten(raw_trips,     "Trips"),
        "SafetyEvents":   df_safety,
        "HOS_Logs":       flatten(raw_hos,       "HOS_Logs"),
        "HOS_Violations": df_hosv,
        "DVIRs":          flatten(raw_dvirs,     "DVIRs"),
        "DVIR_Defects":   df_dvir_defects,
        "EngineIdle":     df_idle,
        "DriverSafetyScores":    df_driver_scores,
        "DriverSafetyScoresMtd": df_driver_scores_mtd,
        "CoachingSessions":      df_coaching,
        "TrainingAssignments":   df_training,
        **ifta_sheets,
    }

    output_path = output_dir / "Samsara_Master.xlsx"
    write_samsara_xlsx(sheets, output_path)

    log.info("=" * 60)
    log.info("SUCCESS — output: %s", output_path.resolve())
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
