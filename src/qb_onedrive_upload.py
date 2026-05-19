"""Upload all QB Excel files from QB_OUTPUT_DIR to OneDrive/QuickBooks folder.

Reuses the Graph API helpers from onedrive_upload.py.

Required env vars (same Azure app registration as Alvys):
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
    QB_OUTPUT_DIR   — directory containing QB_*.xlsx files
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .onedrive_upload import ensure_folder, get_required, get_token, upload_file

log = logging.getLogger("qb_onedrive_upload")

ONEDRIVE_FOLDER = "QuickBooks"


def main() -> None:
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

    output_dir = Path(os.environ.get("QB_OUTPUT_DIR", "output/quickbooks"))
    if not output_dir.exists():
        log.error("QB output directory not found: %s", output_dir)
        sys.exit(1)

    xlsx_files = sorted(output_dir.glob("QB_*.xlsx"))
    if not xlsx_files:
        log.error("No QB_*.xlsx files found in %s", output_dir)
        sys.exit(1)

    log.info("=" * 55)
    log.info("Uploading %d QB files to OneDrive/%s", len(xlsx_files), ONEDRIVE_FOLDER)
    log.info("=" * 55)

    token = get_token(tenant_id, client_id, client_secret)
    ensure_folder(token, user_upn, ONEDRIVE_FOLDER)

    for file_path in xlsx_files:
        upload_file(
            token=token,
            user_upn=user_upn,
            folder_path=ONEDRIVE_FOLDER,
            filename=file_path.name,
            file_path=file_path,
        )

    log.info("=" * 55)
    log.info("✓ All QB files uploaded to OneDrive/%s", ONEDRIVE_FOLDER)
    log.info("=" * 55)


if __name__ == "__main__":
    main()
