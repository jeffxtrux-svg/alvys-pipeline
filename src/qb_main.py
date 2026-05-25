"""QuickBooks data pull — loops all 5 XFreight companies, writes Excel files.

Each report type becomes one Excel file with a "Company" column so Power BI
can slice across entities. Token rotation is handled automatically: after each
company pull the new refresh token is written back to the GitHub Secret via
the gh CLI (requires GH_TOKEN env var set to a PAT with repo/secrets scope).

Required environment variables (GitHub Secrets):
    QB_CLIENT_ID                  — Intuit app production Client ID
    QB_CLIENT_SECRET              — Intuit app production Client Secret
    QB_XTRUX_REFRESH_TOKEN        — X-Trux Inc refresh token
    QB_TRUKWAY_REFRESH_TOKEN      — Truk-Way Leasing refresh token
    QB_XLINX_REFRESH_TOKEN        — X-Linx Inc refresh token
    QB_NJ_TRAILERS_REFRESH_TOKEN  — N&J Trailers (add when ATY grants access)
    QB_NJ_PROPERTIES_REFRESH_TOKEN— N&J Properties (add when ATY grants access)
    GH_TOKEN / GH_PAT             — GitHub PAT for secret rotation

Optional:
    QB_OUTPUT_DIR                 — output directory (default: output/quickbooks)
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .qb_client import QBClient
from .qb_reports import (
    ENTITY_QUERIES,
    REPORT_CONFIGS,
    fetch_ap_history,
    fetch_ar_history,
    fetch_entity,
    fetch_report,
)

log = logging.getLogger("qb_main")


def _companies() -> list[dict]:
    """Return company config. Realm IDs are not sensitive — they're just QB company IDs."""
    return [
        {
            "name": "X-Trux Inc",
            "realm_id": "9341454573269252",
            "token_env": "QB_XTRUX_REFRESH_TOKEN",
            "secret_name": "QB_XTRUX_REFRESH_TOKEN",
        },
        {
            "name": "Truk-Way Leasing",
            "realm_id": "9341454569556134",
            "token_env": "QB_TRUKWAY_REFRESH_TOKEN",
            "secret_name": "QB_TRUKWAY_REFRESH_TOKEN",
        },
        {
            "name": "X-Linx Inc",
            "realm_id": "9341454574046601",
            "token_env": "QB_XLINX_REFRESH_TOKEN",
            "secret_name": "QB_XLINX_REFRESH_TOKEN",
        },
        {
            "name": "N&J Trailers",
            "realm_id": os.environ.get("QB_NJ_TRAILERS_REALM_ID", ""),
            "token_env": "QB_NJ_TRAILERS_REFRESH_TOKEN",
            "secret_name": "QB_NJ_TRAILERS_REFRESH_TOKEN",
        },
        {
            "name": "N&J Properties",
            "realm_id": os.environ.get("QB_NJ_PROPERTIES_REALM_ID", ""),
            "token_env": "QB_NJ_PROPERTIES_REFRESH_TOKEN",
            "secret_name": "QB_NJ_PROPERTIES_REFRESH_TOKEN",
        },
    ]


def rotate_secret(secret_name: str, new_value: str) -> None:
    """Write the new refresh token back to GitHub Secrets via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "secret", "set", secret_name, "--body", new_value],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            log.info("    Secret %s rotated ✓", secret_name)
        else:
            log.warning("    Secret rotation failed for %s: %s", secret_name, result.stderr.strip())
    except FileNotFoundError:
        log.warning("    gh CLI not found — skipping secret rotation for %s", secret_name)
    except Exception as exc:
        log.warning("    Secret rotation error for %s: %s", secret_name, exc)


def write_excel(dfs: list[pd.DataFrame], path: Path) -> None:
    valid = [df for df in dfs if df is not None and not df.empty]
    if not valid:
        log.warning("No data for %s — skipping", path.name)
        return
    combined = pd.concat(valid, ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_excel(path, index=False)
    log.info("  Wrote %-40s (%d rows)", path.name, len(combined))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    client_id = os.environ.get("QB_CLIENT_ID", "")
    client_secret = os.environ.get("QB_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.error("QB_CLIENT_ID and QB_CLIENT_SECRET must be set")
        sys.exit(1)

    output_dir = Path(os.environ.get("QB_OUTPUT_DIR", "output/quickbooks"))
    output_dir.mkdir(parents=True, exist_ok=True)

    report_dfs: dict[str, list[pd.DataFrame]] = {r: [] for r in REPORT_CONFIGS}
    entity_dfs: dict[str, list[pd.DataFrame]] = {e: [] for e in ENTITY_QUERIES}
    ar_history_dfs: list[pd.DataFrame] = []
    ap_history_dfs: list[pd.DataFrame] = []

    for company in _companies():
        refresh_token = os.environ.get(company["token_env"], "")
        realm_id = company["realm_id"]

        if not refresh_token or not realm_id:
            log.info("Skipping %-20s (no credentials)", company["name"])
            continue

        log.info("=" * 55)
        log.info("Company: %s", company["name"])

        client = QBClient(
            client_id=client_id,
            client_secret=client_secret,
            realm_id=realm_id,
            refresh_token=refresh_token,
        )

        for report_name in REPORT_CONFIGS:
            df = fetch_report(client, report_name, company["name"])
            if df is not None:
                report_dfs[report_name].append(df)

        for entity in ENTITY_QUERIES:
            df = fetch_entity(client, entity, company["name"])
            if df is not None:
                entity_dfs[entity].append(df)

        ar_hist = fetch_ar_history(client, company["name"])
        if ar_hist is not None:
            ar_history_dfs.append(ar_hist)

        ap_hist = fetch_ap_history(client, company["name"])
        if ap_hist is not None:
            ap_history_dfs.append(ap_hist)

        if client.new_refresh_token:
            rotate_secret(company["secret_name"], client.new_refresh_token)

    log.info("=" * 55)
    log.info("Writing Excel files…")

    for report_name, dfs in report_dfs.items():
        write_excel(dfs, output_dir / f"QB_{report_name}.xlsx")

    for entity, dfs in entity_dfs.items():
        write_excel(dfs, output_dir / f"QB_{entity}s.xlsx")

    write_excel(ar_history_dfs, output_dir / "QB_AR_History.xlsx")
    write_excel(ap_history_dfs, output_dir / "QB_AP_History.xlsx")

    log.info("All done ✓")


if __name__ == "__main__":
    main()
