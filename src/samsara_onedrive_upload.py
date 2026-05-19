"""Upload Samsara_Master.xlsx to OneDrive/Samsara/ folder.

Reuses the Graph API helpers from onedrive_upload.py.

Required env vars (same Azure app registration as Alvys):
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
    SAMSARA_OUTPUT_DIR — directory containing Samsara_Master.xlsx
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .onedrive_upload import ensure_folder, get_required, get_token, upload_file

log = logging.getLogger("samsara_onedrive_upload")

ONEDRIVE_FOLDER = "Samsara"


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

    output_dir = Path(os.environ.get("SAMSARA_OUTPUT_DIR", "output/samsara"))
    file_path = output_dir / "Samsara_Master.xlsx"

    if not file_path.exists():
        log.error("File not found: %s", file_path)
        sys.exit(1)

    log.info("=" * 55)
    log.info("Uploading Samsara_Master.xlsx → OneDrive/%s", ONEDRIVE_FOLDER)
    log.info("=" * 55)

    token = get_token(tenant_id, client_id, client_secret)
    ensure_folder(token, user_upn, ONEDRIVE_FOLDER)
    result = upload_file(
        token=token,
        user_upn=user_upn,
        folder_path=ONEDRIVE_FOLDER,
        filename="Samsara Master.xlsx",
        file_path=file_path,
    )

    log.info("=" * 55)
    log.info("✓ Upload complete → %s", result.get("webUrl", "(no URL)"))
    log.info("=" * 55)


if __name__ == "__main__":
    main()
