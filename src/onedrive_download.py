"""Microsoft Graph helpers for listing and downloading files from OneDrive."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import requests

from .onedrive_upload import GRAPH, _enc_path

log = logging.getLogger("onedrive_download")


def list_folder(token: str, user_upn: str, folder_path: str) -> list[dict]:
    """Return file/folder items in a OneDrive folder. Empty list if folder is missing."""
    headers = {"Authorization": f"Bearer {token}"}
    user_enc = quote(user_upn, safe="@.")
    if folder_path:
        url = f"{GRAPH}/users/{user_enc}/drive/root:/{_enc_path(folder_path)}:/children"
    else:
        url = f"{GRAPH}/users/{user_enc}/drive/root/children"

    items: list[dict] = []
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 404:
            log.warning("Folder not found in OneDrive: /%s", folder_path or "(root)")
            return []
        if resp.status_code != 200:
            log.error("List folder failed [%s]: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        body = resp.json()
        items.extend(body.get("value", []))
        url = body.get("@odata.nextLink")
    return items


def download_file(token: str, user_upn: str, item_id: str, dest_path: Path) -> None:
    """Stream-download an item by its driveItem id."""
    headers = {"Authorization": f"Bearer {token}"}
    user_enc = quote(user_upn, safe="@.")
    url = f"{GRAPH}/users/{user_enc}/drive/items/{item_id}/content"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers=headers, stream=True, timeout=300) as resp:
        if resp.status_code != 200:
            log.error("Download failed [%s]: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
