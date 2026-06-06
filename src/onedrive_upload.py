"""Upload Alvys_Master.xlsx to OneDrive via Microsoft Graph API.

Uses the OAuth2 client credentials flow with Application permissions
(Files.ReadWrite.All) granted to the `alvys-pipeline` app registration
in Microsoft Entra.

Environment variables expected (from .env locally or GitHub Secrets in CI):
    AZURE_TENANT_ID        — tenant GUID
    AZURE_CLIENT_ID        — app registration GUID
    AZURE_CLIENT_SECRET    — app secret value
    ONEDRIVE_USER_UPN      — user whose OneDrive we upload to (e.g. jeff@xfreight.net)
    ONEDRIVE_FOLDER_PATH   — folder path inside OneDrive (e.g. "Alvys")
    OUTPUT_DIR             — where the xlsx was written by main.py (default: output)
"""
from __future__ import annotations
import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

log = logging.getLogger("onedrive_upload")

GRAPH = "https://graph.microsoft.com/v1.0"
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB chunks (must be multiple of 320 KiB)


def _enc_path(path: str) -> str:
    """URL-encode each path segment so spaces / special chars work in Graph URLs."""
    # `safe=""` ensures spaces become %20, not '+'
    return "/".join(quote(part, safe="") for part in path.split("/") if part)


def get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }
    log.info("Requesting Microsoft Graph access token…")
    resp = requests.post(url, data=data, timeout=30)
    if resp.status_code != 200:
        log.error("Token request failed [%s]: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
    return resp.json()["access_token"]


def ensure_folder(token: str, user_upn: str, folder_path: str) -> None:
    """Create folder (and any intermediate folders) if it doesn't exist."""
    if not folder_path:
        return  # root, always exists
    headers = {"Authorization": f"Bearer {token}"}
    user_enc = quote(user_upn, safe="@.")
    # check existence
    check_url = f"{GRAPH}/users/{user_enc}/drive/root:/{_enc_path(folder_path)}"
    resp = requests.get(check_url, headers=headers, timeout=30)
    if resp.status_code == 200:
        log.info("Folder /%s exists ✓", folder_path)
        return
    if resp.status_code != 404:
        log.error("Folder check failed [%s]: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
    # walk path, creating each segment
    log.info("Folder /%s missing — creating…", folder_path)
    parent = ""
    for part in folder_path.split("/"):
        if not part:
            continue
        if parent:
            children_url = f"{GRAPH}/users/{user_enc}/drive/root:/{_enc_path(parent)}:/children"
        else:
            children_url = f"{GRAPH}/users/{user_enc}/drive/root/children"
        body = {
            "name": part,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }
        cresp = requests.post(
            children_url,
            headers={**headers, "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        # 409 means already exists — that's fine, keep going
        if cresp.status_code not in (200, 201, 409):
            log.error("Folder create failed [%s]: %s", cresp.status_code, cresp.text[:500])
            cresp.raise_for_status()
        parent = f"{parent}/{part}" if parent else part
        log.info("  ✓ /%s", parent)


def upload_file(
    token: str,
    user_upn: str,
    folder_path: str,
    filename: str,
    file_path: Path,
) -> dict:
    """Upload via resumable upload session (handles files of any size)."""
    headers = {"Authorization": f"Bearer {token}"}
    folder_path = folder_path.strip("/")
    user_enc = quote(user_upn, safe="@.")
    name_enc = quote(filename, safe="")
    if folder_path:
        target = f"/users/{user_enc}/drive/root:/{_enc_path(folder_path)}/{name_enc}"
    else:
        target = f"/users/{user_enc}/drive/root:/{name_enc}"

    file_size = file_path.stat().st_size
    log.info("Uploading %s (%s bytes) to OneDrive: %s/%s",
             filename, f"{file_size:,}", folder_path or "(root)", filename)

    # Always use upload session — handles files of any size cleanly
    session_url = f"{GRAPH}{target}:/createUploadSession"
    session_body = {
        "item": {
            "@microsoft.graph.conflictBehavior": "replace",
            "name": filename,
        }
    }
    # OneDrive occasionally returns 409 nameAlreadyExists when a prior
    # upload session for the same filename hasn't fully closed yet (the
    # session lock typically clears within 30–90s). Retry with backoff
    # before failing the whole run.
    s_resp = None
    for attempt, delay in enumerate((0, 15, 30, 60, 120)):
        if delay:
            log.warning("Upload session lock — retrying in %ds (attempt %d)…", delay, attempt + 1)
            import time; time.sleep(delay)
        s_resp = requests.post(
            session_url,
            headers={**headers, "Content-Type": "application/json"},
            json=session_body,
            timeout=30,
        )
        if s_resp.status_code == 200:
            break
        if s_resp.status_code == 409 and "nameAlreadyExists" in (s_resp.text or ""):
            continue  # transient — retry
        break  # non-retryable error
    if s_resp.status_code != 200:
        log.error("Create upload session failed [%s]: %s",
                  s_resp.status_code, s_resp.text[:500])
        s_resp.raise_for_status()
    upload_url = s_resp.json()["uploadUrl"]
    log.info("Upload session created, streaming chunks…")

    last_resp = None
    with open(file_path, "rb") as f:
        uploaded = 0
        while uploaded < file_size:
            chunk = f.read(CHUNK_SIZE)
            chunk_end = uploaded + len(chunk) - 1
            chunk_headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {uploaded}-{chunk_end}/{file_size}",
            }
            cresp = requests.put(upload_url, headers=chunk_headers,
                                  data=chunk, timeout=120)
            if cresp.status_code not in (200, 201, 202):
                log.error("Chunk upload failed [%s]: %s",
                          cresp.status_code, cresp.text[:500])
                cresp.raise_for_status()
            uploaded += len(chunk)
            pct = uploaded / file_size * 100
            log.info("  %s / %s bytes (%.1f%%)",
                     f"{uploaded:,}", f"{file_size:,}", pct)
            last_resp = cresp
    return last_resp.json() if last_resp else {}


def download_file(token: str, user_upn: str, path: str) -> bytes:
    """Download a file's raw bytes from a user's OneDrive by path."""
    headers = {"Authorization": f"Bearer {token}"}
    user_enc = quote(user_upn, safe="@.")
    url = f"{GRAPH}/users/{user_enc}/drive/root:/{_enc_path(path.strip('/'))}:/content"
    resp = requests.get(url, headers=headers, timeout=180)
    if resp.status_code != 200:
        log.error("Download %s failed [%s]: %s", path, resp.status_code, resp.text[:300])
        resp.raise_for_status()
    return resp.content


def _share_id(share_url: str) -> str:
    """Encode a sharing URL into a Graph share id (u!<base64url>, no padding)."""
    import base64
    url = share_url.split("?", 1)[0]  # drop volatile ?e=... access token
    b64 = base64.urlsafe_b64encode(url.encode("utf-8")).decode("utf-8").rstrip("=")
    return "u!" + b64


def download_shared_file(token: str, share_url: str) -> bytes:
    """Download raw bytes of the driveItem behind a OneDrive/SharePoint sharing URL.

    Resolves the exact shared item, so it's immune to duplicate filenames at the
    same path. Used by the scorecard to read the specific workbook the report uses.
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH}/shares/{_share_id(share_url)}/driveItem/content"
    resp = requests.get(url, headers=headers, timeout=180)
    if resp.status_code != 200:
        log.error("Download shared file failed [%s]: %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
    return resp.content


def get_shared_modified(token: str, share_url: str):
    """lastModifiedDateTime (tz-aware) of the shared driveItem, or None. Fail-soft."""
    from datetime import datetime
    try:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GRAPH}/shares/{_share_id(share_url)}/driveItem"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None
        ts = resp.json().get("lastModifiedDateTime")
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
    except Exception:
        return None


def get_file_modified(token: str, user_upn: str, path: str):
    """Return a file's lastModifiedDateTime (tz-aware datetime) from OneDrive, or
    None if it can't be determined. Fail-soft: used only for a display timestamp."""
    from datetime import datetime
    try:
        headers = {"Authorization": f"Bearer {token}"}
        user_enc = quote(user_upn, safe="@.")
        url = f"{GRAPH}/users/{user_enc}/drive/root:/{_enc_path(path.strip('/'))}"
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None
        ts = resp.json().get("lastModifiedDateTime")
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
    except Exception:
        return None


def get_required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        log.error("Missing required environment variable: %s", key)
        sys.exit(1)
    return val


def main():
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
    folder_path = os.environ.get("ONEDRIVE_FOLDER_PATH", "").strip("/")
    target_filename = os.environ.get("ONEDRIVE_TARGET_FILENAME", "Alvys_Master.xlsx")

    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    file_path = output_dir / "Alvys_Master.xlsx"
    if not file_path.exists():
        log.error("File not found: %s", file_path)
        sys.exit(1)

    log.info("=" * 60)
    log.info("OneDrive upload")
    log.info("  user        : %s", user_upn)
    log.info("  folder      : /%s", folder_path or "(root)")
    log.info("  source file : %s", file_path)
    log.info("=" * 60)

    token = get_token(tenant_id, client_id, client_secret)
    ensure_folder(token, user_upn, folder_path)
    result = upload_file(
        token=token,
        user_upn=user_upn,
        folder_path=folder_path,
        filename=target_filename,
        file_path=file_path,
    )

    web_url = result.get("webUrl", "(no URL in response)")
    log.info("=" * 60)
    log.info("✓ Upload complete")
    log.info("  webUrl: %s", web_url)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
