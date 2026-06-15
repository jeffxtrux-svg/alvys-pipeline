"""Daily SambaSafety refresh — assembles ``SambaSafety_Master.xlsx`` and
uploads it to OneDrive so the scorecard's page 2 stays current.

Two paths, picked by env vars:

  1. **API mode (preferred)** — set ``SAMBASAFETY_API_TOKEN`` (and
     optionally ``SAMBASAFETY_API_BASE_URL``, ``SAMBASAFETY_GROUP_NAME``).
     Pulls drivers, licenses, license status, and existing MVR reports
     directly from SambaSafety. No CSV step. Zero per-refresh cost
     (only reads endpoints, never places new MVR orders).

  2. **CSV-drop fallback** — used automatically when no API token is
     present. Downloads ``risk_index_report.csv`` and
     ``violationsReport.csv`` from OneDrive, merges them via
     ``src.sambasafety_combine``. Bridges the gap during initial
     onboarding, or when the API key is temporarily unavailable.

Either path writes the same two-sheet workbook the scorecard reads:
``Drivers`` + ``Violations`` — so downstream code is unchanged.

Required env (same Azure app as the other refresh jobs):
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN

API-mode env:
    SAMBASAFETY_API_TOKEN        the JWT from the envelope file
    SAMBASAFETY_API_BASE_URL     default "https://api.sambasafety.io"
                                 (use "https://api-demo.sambasafety.io"
                                  to point at the demo environment)
    SAMBASAFETY_GROUP_NAME       optional, default is "all groups merged"
                                 — set this when you have multiple groups
                                 and only want the X-Trux drivers.

Shared env (both paths):
    SAMBASAFETY_FOLDER           default "SambaSafety"
    SAMBASAFETY_OUT_FILE         default "SambaSafety_Master.xlsx"
    SAMBASAFETY_OUTPUT_DIR       default "output/sambasafety"

Run locally:
    python -m src.sambasafety_main
"""
from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .onedrive_upload import (
    download_file, ensure_folder, get_required, get_token, upload_file,
)
from .sambasafety_combine import combine_to_workbook
from .sambasafety_client import SambaSafetyClient, SambaSafetyError


log = logging.getLogger("sambasafety_main")


# ----------------------------------------------------------------------
# Workbook assembly from API responses
# ----------------------------------------------------------------------
def _full_name(person: dict) -> str:
    parts = []
    for k in ("firstName", "middleName", "lastName"):
        v = (person.get(k) or "").strip()
        if v:
            parts.append(v)
    return " ".join(parts)


def _pick(d: dict, *keys, default=None):
    """First non-empty value for the listed keys (case-insensitive)."""
    if not isinstance(d, dict):
        return default
    lower = {k.lower(): k for k in d.keys()}
    for k in keys:
        actual = lower.get(k.lower())
        if actual is None:
            continue
        v = d.get(actual)
        if v not in (None, "", []):
            return v
    return default


def _violations_from_mvr(mvr: dict, driver_name: str) -> list[dict]:
    """Pull violation rows out of a single MVR report.

    SambaSafety nests violations in a few different places depending on
    the MVR product (Activity vs Intelligent vs Transactional). Probe
    each in turn and yield whatever's there. Defensive against missing
    keys — soft-fails to an empty list rather than raising."""
    if not isinstance(mvr, dict):
        return []
    candidates = []
    for k in ("violations", "convictions", "accidents", "events"):
        v = mvr.get(k)
        if isinstance(v, list):
            candidates.extend(v)
    # Some MVR products nest violations under a `.report` or .mvrReport key
    for nest_key in ("report", "mvrReport", "mvrOrderResult", "Record"):
        nested = mvr.get(nest_key)
        if isinstance(nested, dict):
            for k in ("violations", "convictions", "accidents", "events"):
                v = nested.get(k)
                if isinstance(v, list):
                    candidates.extend(v)
    out = []
    for v in candidates:
        if not isinstance(v, dict):
            continue
        out.append({
            "Driver Name": driver_name,
            "Date": _pick(v, "violationDate", "convictionDate",
                          "offenseDate", "date"),
            "Type": _pick(v, "violationDescription", "description",
                          "type", "offense"),
            "Points": _pick(v, "violationScore", "points", "score"),
            "State": _pick(v, "state", "jurisdiction"),
            "Severity": _pick(v, "severity", "level", "seriousness"),
        })
    return out


def assemble_workbook_from_api(client: SambaSafetyClient,
                               group_name_filter: str | None = None) -> bytes:
    """Build ``SambaSafety_Master.xlsx`` directly from the API. Same
    two-sheet schema the CSV path produces, so downstream is unchanged.

    Strategy (all free):
      1. List groups; if ``group_name_filter`` set, narrow to matching ones.
      2. For each group: list people.
      3. For each person: list licenses, fetch license status, list MVRs,
         read the most recent MVR (for license expiration + violations).
      4. Compose the Drivers + Violations sheets.
    """
    groups = client.list_groups()
    log.info("Groups: %d total", len(groups))
    for g in groups:
        log.info("  - %s (id=%s)", g.get("groupName"), g.get("groupId"))

    if group_name_filter:
        before = len(groups)
        nf = group_name_filter.strip().lower()
        groups = [g for g in groups
                  if nf in (g.get("groupName") or "").lower()]
        log.info("Filtered to %d groups containing %r (was %d)",
                 len(groups), group_name_filter, before)

    drivers_rows: list[dict] = []
    violations_rows: list[dict] = []

    for g in groups:
        gid = g.get("groupId")
        gname = g.get("groupName") or "(unnamed)"
        if not gid:
            continue
        people = client.list_people_in_group(gid)
        log.info("Group %s: %d people", gname, len(people))
        for person in people:
            person_id = person.get("personId")
            if not person_id:
                continue
            name = _full_name(person)
            if not name:
                continue
            if (person.get("archiveStatus") is True
                    or str(person.get("archiveStatus", "")).lower() == "true"):
                continue   # terminated / archived driver — skip

            licenses = []
            try:
                licenses = client.list_licenses_for_person(person_id)
            except SambaSafetyError as e:
                log.warning("  %s: licenses fetch failed (%s) — skipping driver",
                            name, e)
                continue

            # Pick the CDL if any, else the first license.
            cdl = next(
                (lic for lic in licenses
                 if lic.get("CDL") is True or lic.get("cdl") is True),
                None)
            primary = cdl or (licenses[0] if licenses else {})
            license_id = primary.get("licenseId")
            license_num = primary.get("licenseNumber", "")
            license_state = primary.get("licenseState", "")

            status_obj = None
            if license_id:
                try:
                    status_obj = client.get_license_status(license_id)
                except SambaSafetyError as e:
                    log.warning("  %s: status fetch failed (%s)", name, e)
            status_txt = (status_obj or {}).get("status", "Unknown")

            # Read existing MVRs for license expiration + violations.
            # Reading is free; we never call a Place-Order endpoint.
            license_expiration = None
            risk_score = None
            risk_category = ""
            try:
                mvrs = client.list_mvrs_for_person(person_id)
            except SambaSafetyError as e:
                log.warning("  %s: MVR list failed (%s)", name, e)
                mvrs = []
            if mvrs:
                mvrs_sorted = sorted(
                    mvrs,
                    key=lambda m: m.get("mvrDateTime", ""),
                    reverse=True)
                # Pull violations from every MVR; pull expiration / risk
                # from the most recent one.
                for i, m in enumerate(mvrs_sorted):
                    mvr_id = m.get("mvrId") or m.get("reportId")
                    if not mvr_id:
                        continue
                    try:
                        full = client.get_mvr_report(mvr_id)
                    except SambaSafetyError as e:
                        log.warning("  %s: MVR %s fetch failed (%s)",
                                    name, mvr_id, e)
                        continue
                    if full is None:
                        continue
                    violations_rows.extend(_violations_from_mvr(full, name))
                    if i == 0:
                        license_expiration = _pick(
                            full, "licenseExpirationDate",
                            "licenseExpiration", "expirationDate",
                            "expiresAt")
                        risk_score = _pick(
                            full, "riskScore", "score", "currentRiskScore")
                        risk_category = _pick(
                            full, "riskCategory", "category",
                            "riskLevel", default="")

            drivers_rows.append({
                "Driver Name": name,
                "License Number": license_num,
                "License State": license_state,
                "License Status": status_txt,
                "License Expiration": license_expiration,
                "Risk Score": risk_score,
                "Risk Category": risk_category,
            })

    log.info("Assembled %d driver row(s) and %d violation row(s)",
             len(drivers_rows), len(violations_rows))

    drivers_df = pd.DataFrame(drivers_rows, columns=[
        "Driver Name", "License Number", "License State", "License Status",
        "License Expiration", "Risk Score", "Risk Category",
    ])
    if "License Expiration" in drivers_df.columns:
        drivers_df["License Expiration"] = pd.to_datetime(
            drivers_df["License Expiration"], errors="coerce")
    violations_df = pd.DataFrame(violations_rows, columns=[
        "Driver Name", "Date", "Type", "Points", "State", "Severity",
    ]).sort_values("Date", ascending=False, na_position="last") if violations_rows else \
        pd.DataFrame(columns=["Driver Name", "Date", "Type", "Points",
                              "State", "Severity"])
    if "Date" in violations_df.columns and not violations_df.empty:
        violations_df["Date"] = pd.to_datetime(
            violations_df["Date"], errors="coerce")

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        drivers_df.to_excel(writer, sheet_name="Drivers", index=False)
        violations_df.to_excel(writer, sheet_name="Violations", index=False)
    return buf.getvalue()


# ----------------------------------------------------------------------
# CSV-drop fallback (existing behavior, untouched)
# ----------------------------------------------------------------------
def _build_from_csv(token: str, user_upn: str, folder: str) -> bytes:
    risk_file = os.environ.get("SAMBASAFETY_RISK_INDEX_FILE",
                               "risk_index_report.csv")
    viol_file = os.environ.get("SAMBASAFETY_VIOLATIONS_FILE",
                               "violationsReport.csv")
    csa_file = os.environ.get("SAMBASAFETY_CSA_FILE",
                              "CSA2010 Preview Scorecard.csv")
    invalid_file = os.environ.get("SAMBASAFETY_INVALID_FILE",
                                  "InvalidLicenseReport.csv")
    risk_path = f"{folder}/{risk_file}"
    viol_path = f"{folder}/{viol_file}"
    csa_path = f"{folder}/{csa_file}"
    invalid_path = f"{folder}/{invalid_file}"
    log.info("Downloading %s ...", risk_path)
    risk_bytes = download_file(token, user_upn, risk_path)
    log.info("  -> %d bytes", len(risk_bytes))
    log.info("Downloading %s ...", viol_path)
    viol_bytes = download_file(token, user_upn, viol_path)
    log.info("  -> %d bytes", len(viol_bytes))
    csa_bytes = None
    log.info("Downloading %s ...", csa_path)
    try:
        csa_bytes = download_file(token, user_upn, csa_path)
        log.info("  -> %d bytes", len(csa_bytes))
    except Exception as e:
        log.warning("  CSA scorecard CSV not found (%s) — CSA Scorecard sheet will be omitted", e)
    invalid_bytes = None
    log.info("Downloading %s ...", invalid_path)
    try:
        invalid_bytes = download_file(token, user_upn, invalid_path)
        log.info("  -> %d bytes", len(invalid_bytes))
    except Exception as e:
        log.warning("  Invalid License Report not found (%s) — Invalid Licenses sheet will be empty", e)
    return combine_to_workbook(risk_bytes, viol_bytes, csa_csv=csa_bytes,
                               invalid_csv=invalid_bytes)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    tenant_id = get_required("AZURE_TENANT_ID")
    client_id = get_required("AZURE_CLIENT_ID")
    client_secret = get_required("AZURE_CLIENT_SECRET")
    user_upn = get_required("ONEDRIVE_USER_UPN")

    folder = os.environ.get("SAMBASAFETY_FOLDER", "SambaSafety").strip("/")
    out_file = os.environ.get("SAMBASAFETY_OUT_FILE",
                              "SambaSafety_Master.xlsx")
    output_dir = Path(os.environ.get(
        "SAMBASAFETY_OUTPUT_DIR", "output/sambasafety"))

    api_token = os.environ.get("SAMBASAFETY_API_TOKEN", "").strip()
    api_base = (os.environ.get("SAMBASAFETY_API_BASE_URL", "").strip()
                or "https://api.sambasafety.io")
    # JWT tokens (eyJ...) are sent as Authorization: Bearer; hex/opaque keys
    # are sent as X-Api-Key. Default to Bearer because the token in the
    # envelope file is a JWT.
    auth_scheme = (os.environ.get("SAMBASAFETY_AUTH_SCHEME", "").strip()
                   or "bearer").lower()
    group_filter = os.environ.get("SAMBASAFETY_GROUP_NAME", "").strip() or None

    log.info("=" * 55)
    log.info("SambaSafety refresh")
    if api_token:
        log.info("  mode      : API (%s)", api_base)
        log.info("  auth      : %s", auth_scheme)
        if group_filter:
            log.info("  group     : %s", group_filter)
        log.info("  out file  : OneDrive/%s/%s", folder, out_file)
    else:
        log.info("  mode      : CSV drop (no SAMBASAFETY_API_TOKEN set)")
        log.info("  source    : OneDrive/%s/", folder)
    log.info("=" * 55)

    od_token = get_token(tenant_id, client_id, client_secret)

    if api_token:
        client = SambaSafetyClient(
            api_token, base_url=api_base, auth_scheme=auth_scheme)
        try:
            xlsx_bytes = assemble_workbook_from_api(
                client, group_name_filter=group_filter)
        except SambaSafetyError as e:
            err = str(e)
            if "HTTP 401" in err or "HTTP 403" in err:
                log.error(
                    "Auth rejected by SambaSafety (%s). Check that:\n"
                    "  1. SAMBASAFETY_API_TOKEN matches the env in "
                    "SAMBASAFETY_API_BASE_URL (demo token vs prod URL is "
                    "a frequent cause).\n"
                    "  2. SAMBASAFETY_AUTH_SCHEME — JWT-looking tokens "
                    "(eyJ...) need 'bearer' (default); hex/opaque keys "
                    "need 'apikey'.\n"
                    "  3. The token hasn't expired (SambaSafety bearer "
                    "tokens live ~1 hour from /oauth2/v1/token; envelope "
                    "tokens may be longer-lived).", err)
            # A dead/expired token shouldn't kill the refresh while the
            # CSV drops are sitting in OneDrive — fall back to CSV mode
            # (the API endpoints return 401/403, or 404 "Forbidden" for
            # retired accounts) and let the workbook build from those.
            log.warning("API mode failed (%s) — falling back to CSV-drop mode.", err)
            xlsx_bytes = _build_from_csv(od_token, user_upn, folder)
    else:
        xlsx_bytes = _build_from_csv(od_token, user_upn, folder)

    output_dir.mkdir(parents=True, exist_ok=True)
    local_path = output_dir / out_file
    local_path.write_bytes(xlsx_bytes)
    log.info("Wrote local artifact %s (%d bytes)",
             local_path, len(xlsx_bytes))

    log.info("Uploading -> OneDrive/%s/%s", folder, out_file)
    ensure_folder(od_token, user_upn, folder)
    result = upload_file(
        token=od_token, user_upn=user_upn,
        folder_path=folder, filename=out_file, file_path=local_path,
    )

    log.info("=" * 55)
    log.info("Upload complete -> %s", result.get("webUrl", "(no URL)"))
    log.info("=" * 55)
    return 0


if __name__ == "__main__":
    sys.exit(main())
