"""SharePoint Bills Inbox client for the bill archive tool.

Microsoft Graph calls for:
- Library discovery (site + drive ID + list ID resolution)
- Column setup (auto-creates all required metadata columns)
- Folder hierarchy creation (OperatingCompany/Year)
- PDF upload (resumable session, same pattern as onedrive_upload.py)
- List item metadata PATCH (custom columns for searchability)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from urllib.parse import quote

import requests

log = logging.getLogger("bill_archive.sp")
GRAPH = "https://graph.microsoft.com/v1.0"
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB

# ------------------------------------------------------------------
# Column definitions for --setup-columns
# Graph API column types: text, number, dateTime, choice, boolean
# ------------------------------------------------------------------
COLUMN_DEFINITIONS = [
    {"name": "Vendor",             "text": {}},
    {"name": "InvoiceNumber",      "text": {}},
    {"name": "InvoiceDate",        "dateTime": {"displayAs": "dateOnly", "format": "dateOnly"}},
    {"name": "DueDate",            "dateTime": {"displayAs": "dateOnly", "format": "dateOnly"}},
    {"name": "Amount",             "number":   {"decimalPlaces": "two"}},
    {
        "name": "OperatingCompany",
        "choice": {
            "allowTextEntry": False,
            "choices": ["X-Trux", "X-Linx", "Truk-Way"],
            "displayAs": "dropDownMenu",
        },
    },
    {
        "name": "BillType",
        "choice": {
            "allowTextEntry": False,
            "choices": [
                "DOT Inspection", "PM Inspection", "Maintenance & Repairs",
                "Parts", "Tires", "Fuel", "Insurance", "Registration",
                "Permits", "Tolls", "Drug Testing", "Driver Medical",
                "Trailer Rental", "Office/Admin", "Other",
            ],
            "displayAs": "dropDownMenu",
        },
    },
    {"name": "UnitNumber",         "text": {}},
    {
        "name": "EquipmentType",
        "choice": {
            "allowTextEntry": False,
            "choices": ["Tractor", "Trailer", "Fleet/None"],
            "displayAs": "dropDownMenu",
        },
    },
    {"name": "ServiceDescription", "text": {"allowMultipleLines": True, "linesForEditing": 3}},
    {"name": "ExpirationDate",     "dateTime": {"displayAs": "dateOnly", "format": "dateOnly"}},
    {
        "name": "Status",
        "choice": {
            "allowTextEntry": False,
            "choices": [
                "Archived", "Archive-Needs-Review",
                "Extracted", "Needs Review", "Approved", "Pushed to Ramp",
            ],
            "displayAs": "dropDownMenu",
        },
    },
    {"name": "ArchiveMode",           "boolean": {}},
    {
        "name": "ExtractionConfidence",
        "choice": {
            "allowTextEntry": False,
            "choices": ["High", "Medium", "Low"],
            "displayAs": "dropDownMenu",
        },
    },
    {"name": "MissingFields",  "text": {}},
    {"name": "FileHash",       "text": {}},
    {"name": "SourceFile",     "text": {}},
]


class BillsInboxClient:
    def __init__(self, token: str, site_hostname: str, library_name: str):
        self.token = token
        self.site_hostname = site_hostname.rstrip("/")
        self.library_name = library_name
        self._site_id: str | None = None
        self._drive_id: str | None = None
        self._list_id: str | None = None
        self._folder_cache: set[str] = set()

    @property
    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    # ------------------------------------------------------------------
    # Discovery — resolves site ID, drive ID, and list ID
    # ------------------------------------------------------------------
    def discover(self) -> None:
        """Resolve site, drive, and list IDs. Must call before any other operation."""
        # Site
        resp = requests.get(
            f"{GRAPH}/sites/{self.site_hostname}", headers=self._h, timeout=30
        )
        if resp.status_code != 200:
            log.error("SharePoint site lookup failed [%d]: %s",
                      resp.status_code, resp.text[:300])
        resp.raise_for_status()
        self._site_id = resp.json()["id"]
        log.info("  Site ID  : %s", self._site_id)

        # Drive (document library)
        resp = requests.get(
            f"{GRAPH}/sites/{self._site_id}/drives", headers=self._h, timeout=30
        )
        resp.raise_for_status()
        drives = resp.json().get("value", [])
        for drive in drives:
            if drive.get("name", "").lower() == self.library_name.lower():
                self._drive_id = drive["id"]
                log.info("  Drive ID : %s  (%s)", self._drive_id, self.library_name)
                break
        if not self._drive_id:
            available = [d.get("name") for d in drives]
            raise RuntimeError(
                f"Library '{self.library_name}' not found on {self.site_hostname}. "
                f"Available drives: {available}"
            )

        # List ID (needed for column creation)
        resp = requests.get(
            f"{GRAPH}/sites/{self._site_id}/lists",
            headers=self._h,
            timeout=30,
        )
        if resp.status_code == 200:
            for lst in resp.json().get("value", []):
                if lst.get("displayName", "").lower() == self.library_name.lower():
                    self._list_id = lst["id"]
                    log.info("  List ID  : %s", self._list_id)
                    break
        if not self._list_id:
            log.warning("Could not resolve list ID for '%s' — column setup unavailable",
                        self.library_name)

    # ------------------------------------------------------------------
    # Column setup
    # ------------------------------------------------------------------
    def setup_columns(self) -> tuple[int, int]:
        """Create all required columns in the Bills Inbox library.

        Returns (created_count, skipped_count).
        Skips columns that already exist (409 Conflict).
        Requires Sites.Manage.All or Sites.FullControl.All on the Azure app.
        """
        if not self._list_id:
            raise RuntimeError(
                "List ID not resolved — ensure the library name is correct and "
                "the app has Sites.Manage.All permission."
            )

        created = skipped = 0
        url = f"{GRAPH}/sites/{self._site_id}/lists/{self._list_id}/columns"

        # Fetch existing column names so we can report accurately
        existing: set[str] = set()
        resp = requests.get(url, headers=self._h, timeout=30)
        if resp.status_code == 200:
            for col in resp.json().get("value", []):
                existing.add(col.get("name", "").lower())

        for col_def in COLUMN_DEFINITIONS:
            col_name = col_def["name"]
            if col_name.lower() in existing:
                log.info("  %-26s already exists — skipped", col_name)
                skipped += 1
                continue
            resp = requests.post(
                url,
                headers={**self._h, "Content-Type": "application/json"},
                json=col_def,
                timeout=30,
            )
            if resp.status_code in (200, 201):
                log.info("  %-26s ✓ created", col_name)
                created += 1
            elif resp.status_code == 409:
                log.info("  %-26s already exists — skipped", col_name)
                skipped += 1
            else:
                log.warning("  %-26s failed [%d]: %s",
                            col_name, resp.status_code, resp.text[:200])

        return created, skipped

    def list_existing_columns(self) -> list[str]:
        """Return display names of all existing columns (for --test diagnostics)."""
        if not self._list_id:
            return []
        resp = requests.get(
            f"{GRAPH}/sites/{self._site_id}/lists/{self._list_id}/columns",
            headers=self._h,
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        return [c.get("name", "") for c in resp.json().get("value", [])]

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------
    def ensure_folder(self, folder_path: str) -> None:
        """Create folder hierarchy if it doesn't exist (e.g. 'X-Trux/2023')."""
        if folder_path in self._folder_cache:
            return
        check = requests.get(
            f"{GRAPH}/drives/{self._drive_id}/root:/{_enc(folder_path)}",
            headers=self._h,
            timeout=30,
        )
        if check.status_code == 200:
            self._folder_cache.add(folder_path)
            return

        parent = ""
        for part in folder_path.split("/"):
            if not part:
                continue
            current = f"{parent}/{part}" if parent else part
            if current in self._folder_cache:
                parent = current
                continue
            url = (
                f"{GRAPH}/drives/{self._drive_id}/root:/{_enc(parent)}:/children"
                if parent
                else f"{GRAPH}/drives/{self._drive_id}/root/children"
            )
            resp = requests.post(
                url,
                headers={**self._h, "Content-Type": "application/json"},
                json={"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
                timeout=30,
            )
            if resp.status_code not in (200, 201, 409):
                resp.raise_for_status()
            self._folder_cache.add(current)
            parent = current
        log.debug("Folder ready: %s", folder_path)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    def upload_pdf(self, folder_path: str, filename: str, file_path: Path) -> str:
        """Upload PDF via resumable session. Returns Graph item ID."""
        assert self._drive_id, "call discover() first"
        file_size = file_path.stat().st_size
        name_enc = quote(filename, safe="")
        target = f"/drives/{self._drive_id}/root:/{_enc(folder_path)}/{name_enc}"

        s_resp = None
        for attempt, delay in enumerate((0, 15, 30, 60)):
            if delay:
                log.warning("Upload session lock — retrying in %ds (attempt %d)", delay, attempt)
                time.sleep(delay)
            s_resp = requests.post(
                f"{GRAPH}{target}:/createUploadSession",
                headers={**self._h, "Content-Type": "application/json"},
                json={"item": {
                    "@microsoft.graph.conflictBehavior": "replace",
                    "name": filename,
                }},
                timeout=30,
            )
            if s_resp.status_code == 200:
                break
            if s_resp.status_code == 409 and "nameAlreadyExists" in (s_resp.text or ""):
                continue
            break
        s_resp.raise_for_status()
        upload_url = s_resp.json()["uploadUrl"]

        last_resp: requests.Response | None = None
        with open(file_path, "rb") as fh:
            sent = 0
            while sent < file_size:
                chunk = fh.read(CHUNK_SIZE)
                end = sent + len(chunk) - 1
                r = requests.put(
                    upload_url,
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {sent}-{end}/{file_size}",
                    },
                    data=chunk,
                    timeout=120,
                )
                if r.status_code not in (200, 201, 202):
                    r.raise_for_status()
                sent += len(chunk)
                last_resp = r

        item_id = (last_resp.json() if last_resp else {}).get("id", "")
        log.debug("Uploaded %s → item %s", filename, item_id)
        return item_id

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    def set_metadata(self, item_id: str, fields: dict) -> bool:
        """PATCH custom columns on the uploaded list item. Fail-soft."""
        url = f"{GRAPH}/drives/{self._drive_id}/items/{item_id}/listItem/fields"
        resp = requests.patch(
            url,
            headers={**self._h, "Content-Type": "application/json"},
            json=fields,
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            log.warning(
                "Metadata PATCH failed [%d] on item %s: %s",
                resp.status_code,
                item_id[:12],
                resp.text[:300],
            )
            return False
        return True


def _enc(path: str) -> str:
    """URL-encode each segment of a path for Graph API calls."""
    return "/".join(quote(p, safe="") for p in path.split("/") if p)
