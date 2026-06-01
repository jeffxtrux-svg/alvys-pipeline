"""Daily SambaSafety refresh.

Reads the two raw CSV exports from OneDrive's SambaSafety folder, merges them
into ``SambaSafety_Master.xlsx`` (via ``src.sambasafety_combine``), and uploads
the result back to the same folder so the scorecard's page 9 stays current.

Until the SambaSafety API is wired up, the two CSVs land in OneDrive via one
of: (a) Power Automate flow saving the daily emails' attachments, (b) Outlook
rule, or (c) manual drop. This module is the next step in that pipeline — it
turns the raw exports into the workbook the scorecard reads, on a daily cron.

Required env (same Azure app as the other refresh jobs):
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
Optional:
    SAMBASAFETY_FOLDER            default "SambaSafety"
    SAMBASAFETY_RISK_INDEX_FILE   default "risk_index_report.csv"
    SAMBASAFETY_VIOLATIONS_FILE   default "violationsReport.csv"
    SAMBASAFETY_OUT_FILE          default "SambaSafety_Master.xlsx"
    SAMBASAFETY_OUTPUT_DIR        default "output/sambasafety" (local artifact)

Run locally:
    python -m src.sambasafety_main
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .onedrive_upload import (
    download_file, ensure_folder, get_required, get_token, upload_file,
)
from .sambasafety_combine import combine_to_workbook


log = logging.getLogger("sambasafety_main")


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
    risk_file = os.environ.get("SAMBASAFETY_RISK_INDEX_FILE", "risk_index_report.csv")
    viol_file = os.environ.get("SAMBASAFETY_VIOLATIONS_FILE", "violationsReport.csv")
    out_file = os.environ.get("SAMBASAFETY_OUT_FILE", "SambaSafety_Master.xlsx")
    output_dir = Path(os.environ.get("SAMBASAFETY_OUTPUT_DIR", "output/sambasafety"))

    risk_path = f"{folder}/{risk_file}"
    viol_path = f"{folder}/{viol_file}"

    log.info("=" * 55)
    log.info("SambaSafety refresh - reading from OneDrive/%s/", folder)
    log.info("=" * 55)

    token = get_token(tenant_id, client_id, client_secret)

    log.info("Downloading %s ...", risk_path)
    risk_bytes = download_file(token, user_upn, risk_path)
    log.info("  -> %d bytes", len(risk_bytes))

    log.info("Downloading %s ...", viol_path)
    viol_bytes = download_file(token, user_upn, viol_path)
    log.info("  -> %d bytes", len(viol_bytes))

    log.info("Combining into %s ...", out_file)
    xlsx_bytes = combine_to_workbook(risk_bytes, viol_bytes)

    output_dir.mkdir(parents=True, exist_ok=True)
    local_path = output_dir / out_file
    local_path.write_bytes(xlsx_bytes)
    log.info("Wrote local artifact %s (%d bytes)", local_path, len(xlsx_bytes))

    log.info("Uploading -> OneDrive/%s/%s", folder, out_file)
    ensure_folder(token, user_upn, folder)
    result = upload_file(
        token=token, user_upn=user_upn,
        folder_path=folder, filename=out_file, file_path=local_path,
    )

    log.info("=" * 55)
    log.info("Upload complete -> %s", result.get("webUrl", "(no URL)"))
    log.info("=" * 55)
    return 0


if __name__ == "__main__":
    sys.exit(main())
