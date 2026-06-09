"""Bill Archive Tool — bulk-import historical PDFs into SharePoint Bills Inbox.

Scans a source folder (selected at run time via --source), extracts metadata
from each PDF using Claude, cross-checks unit numbers against the Alvys fleet,
and uploads every bill into Bills Inbox/{OperatingCompany}/{Year}/ with full
column metadata so they are searchable in SharePoint.

Archive mode rules
------------------
- Every bill gets Status = "Archived" if all 5 required fields are present:
    Vendor, Amount, InvoiceDate, OperatingCompany, UnitNumber (or "FLEET")
- If any required field is missing the bill gets Status = "Archive-Needs-Review"
  and is listed in the post-run CSV so someone can fill in the gaps via
  SharePoint column editing.
- Bills that have already been processed (matched by SHA-256 hash stored in
  the manifest) are skipped — safe to re-run after failures or interruptions.

Usage
-----
    python -m src.bill_archive_main --source /path/to/historical/bills

    # dry-run (extract + validate, no uploads)
    python -m src.bill_archive_main --source /path --dry-run

    # adjust workers (default 4)
    python -m src.bill_archive_main --source /path --workers 2

Environment variables (same .env as the rest of the pipeline)
--------------------------------------------------------------
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET  — Graph auth
    ANTHROPIC_API_KEY                                       — Claude extraction
    ALVYS_CLIENT_ID, ALVYS_CLIENT_SECRET                   — fleet lookup (optional)
    BILLS_INBOX_SITE_HOST   default: xfreightnet.sharepoint.com
    BILLS_INBOX_LIBRARY     default: Bills Inbox
    ARCHIVE_MANIFEST_PATH   default: output/bill_archive_manifest.json
    ARCHIVE_LOG_DIR         default: output
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger("bill_archive")

# ------------------------------------------------------------------
# Required fields — a bill must have ALL of these to reach "Archived"
# "FLEET" is accepted as UnitNumber for company-wide bills (insurance etc.)
# ------------------------------------------------------------------
REQUIRED_FIELDS = ("vendor", "amount", "invoice_date", "operating_company", "unit_number")

# Canonical operating company names (Claude maps variations to these)
COMPANIES = {"X-Trux", "X-Linx", "Truk-Way"}

# Alvys fleet → operating company
FLEET_TO_COMPANY: dict[str, str] = {
    "truk-way leasing llc": "Truk-Way",
    "truk-way leasing": "Truk-Way",
    "cds express": "X-Trux",
    "owner ops": "X-Trux",
    "x-trux": "X-Trux",
    "x-linx": "X-Linx",
}

# SharePoint column internal names → our field names
# Edit this mapping if your Bills Inbox library uses different column names.
SP_COLUMN_MAP = {
    "Vendor":               "vendor",
    "InvoiceNumber":        "invoice_number",
    "InvoiceDate":          "invoice_date",
    "DueDate":              "due_date",
    "Amount":               "amount",
    "OperatingCompany":     "operating_company",
    "BillType":             "bill_type",
    "UnitNumber":           "unit_number",
    "EquipmentType":        "equipment_type",
    "ServiceDescription":   "service_description",
    "ExpirationDate":       "expiration_date",
    "Status":               "status",
    "ArchiveMode":          "archive_mode",
    "ExtractionConfidence": "confidence",
    "MissingFields":        "missing_fields_str",
    "FileHash":             "file_hash",
    "SourceFile":           "source_file",
}


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------
@dataclass
class BillRecord:
    # File identity
    file_path: Path = field(default=None)
    file_hash: str = ""
    source_file: str = ""

    # Extracted fields
    vendor: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    due_date: str = ""
    amount: float | None = None
    operating_company: str = ""
    bill_type: str = ""
    unit_number: str = ""
    equipment_type: str = ""
    service_description: str = ""
    expiration_date: str = ""
    confidence: str = "Low"

    # Computed
    status: str = "Archive-Needs-Review"
    archive_mode: bool = True
    missing_fields: list = field(default_factory=list)
    missing_fields_str: str = ""
    sharepoint_folder: str = ""
    item_id: str = ""
    error: str = ""

    def validate(self) -> None:
        """Check required fields and set status + missing_fields list."""
        self.missing_fields = []
        for f_name in REQUIRED_FIELDS:
            val = getattr(self, f_name, None)
            if not val and val != 0:
                self.missing_fields.append(f_name)
        self.missing_fields_str = ", ".join(self.missing_fields)
        self.status = "Archived" if not self.missing_fields else "Archive-Needs-Review"

    def to_sp_fields(self) -> dict:
        """Build the SharePoint column payload from this record."""
        fields: dict = {}
        data = asdict(self)
        for sp_col, rec_field in SP_COLUMN_MAP.items():
            val = data.get(rec_field)
            if val is None or val == "" or val == [] or val is False:
                continue
            # Convert float amount to string for SP number column
            if rec_field == "amount" and isinstance(val, float):
                val = round(val, 2)
            fields[sp_col] = val
        return fields


# ------------------------------------------------------------------
# Manifest — checkpoint / resume
# ------------------------------------------------------------------
_manifest_lock = threading.Lock()


def load_manifest(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"processed": {}}


def save_manifest_entry(path: Path, manifest: dict, record: BillRecord) -> None:
    with _manifest_lock:
        manifest["processed"][record.file_hash] = {
            "file": record.source_file,
            "status": record.status,
            "item_id": record.item_id,
            "folder": record.sharepoint_folder,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(manifest, indent=2))


# ------------------------------------------------------------------
# Alvys fleet lookup (optional — skipped if creds absent)
# ------------------------------------------------------------------
def build_fleet_lookup() -> dict[str, dict]:
    """Returns {unit_number_str: {company, equipment_type}} from Alvys.

    Fails softly — if Alvys creds are missing or the API is down, returns {}.
    The archive tool still works; company detection falls back to Claude only.
    """
    client_id = os.environ.get("ALVYS_CLIENT_ID", "")
    client_secret = os.environ.get("ALVYS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.info("ALVYS_CLIENT_ID/SECRET not set — skipping fleet lookup")
        return {}

    try:
        from src.alvys_client import AlvysClient
        client = AlvysClient(client_id, client_secret)

        lookup: dict[str, dict] = {}

        trucks = client.fetch_trucks()
        for t in trucks:
            num = _try(t, ["TruckNum", "TruckNumber", "Number", "Name"])
            if not num:
                continue
            fleet_raw = (_try(t, ["Fleet", "FleetName", "Fleet.Name"]) or "").lower().strip()
            company = FLEET_TO_COMPANY.get(fleet_raw, "X-Trux")
            lookup[str(num).strip()] = {"company": company, "equipment_type": "Tractor"}

        trailers = client.fetch_trailers()
        for t in trailers:
            num = _try(t, ["TrailerNum", "TrailerNumber", "Number", "Name"])
            if not num:
                continue
            lookup[str(num).strip()] = {"company": "X-Trux", "equipment_type": "Trailer"}

        log.info("Alvys fleet lookup: %d trucks + trailers", len(lookup))
        return lookup
    except Exception as e:
        log.warning("Alvys fleet lookup failed (%s) — continuing without it", e)
        return {}


def _try(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k]:
            return d[k]
        # nested dot path
        if "." in k:
            parts = k.split(".", 1)
            sub = d.get(parts[0])
            if isinstance(sub, dict):
                val = sub.get(parts[1])
                if val:
                    return val
    return None


# ------------------------------------------------------------------
# Claude extraction
# ------------------------------------------------------------------
_EXTRACTION_PROMPT = """You are an AP bill/invoice data extractor for XFreight, a trucking company.
Extract structured data from this bill or invoice PDF.

COMPANY IDENTIFICATION — the "Bill To" company will be one of:
- X-Trux (X-TRUX INC, X-TRUX, Inc., X-Trux Inc) — the trucking carrier
- X-Linx (X-LINX INC, X-Linx Inc) — the freight brokerage
- Truk-Way (TRUK-WAY LEASING LLC, Truk-Way Leasing) — equipment leasing entity
- Unknown — if not determinable from the bill

UNIT NUMBERS — look carefully in ALL line items, work order lines, and asset fields:
- Truck unit numbers: 5-digit numbers (e.g. 41182, 42186, 43199, 44201)
- Trailer unit numbers: 3-digit numbers (e.g. 246, 247, 248, 161)
- Format in service invoices: often appears as "248 CPT" where 248 is the unit# and CPT is a tech/labor code
- For company-wide bills (fleet insurance, office supplies) with no specific unit: use "FLEET"

BILL TYPE — pick the single best match:
DOT Inspection | PM Inspection | Maintenance & Repairs | Parts | Tires | Fuel |
Insurance | Registration | Permits | Tolls | Drug Testing | Driver Medical |
Trailer Rental | Office/Admin | Other

EQUIPMENT TYPE — based on the unit number found:
- 3-digit unit → Trailer
- 5-digit unit → Tractor
- FLEET or no unit → Fleet/None

OUTPUT — return ONLY a valid JSON object, no other text:
{
  "vendor": "exact vendor/company name from the bill header, or null",
  "bill_to": "X-Trux" | "X-Linx" | "Truk-Way" | "Unknown",
  "invoice_number": "invoice or work order number, or null",
  "invoice_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "amount": total amount as a number (no $ or commas) or null,
  "unit_number": "unit number string, FLEET, or null",
  "equipment_type": "Tractor" | "Trailer" | "Fleet/None" | null,
  "bill_type": "one of the listed types or null",
  "service_description": "brief description of work or coverage (max 200 chars), or null",
  "expiration_date": "YYYY-MM-DD for insurance/registration policy end date, or null",
  "confidence": "High" | "Medium" | "Low"
}

confidence:
- High = all key fields (vendor, bill_to, invoice_date, amount) clearly present and legible
- Medium = most fields present but one or more inferred or partially legible
- Low = document is unclear, scanned poorly, or major fields missing"""


def extract_with_claude(file_path: Path) -> dict:
    """Send PDF to Claude, parse JSON response. Returns extracted fields dict."""
    import anthropic

    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY

    pdf_bytes = file_path.read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",  # fast + cheap for extraction
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {"type": "text", "text": _EXTRACTION_PROMPT},
                    ],
                }
            ],
        )
        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("Claude returned non-JSON for %s: %s", file_path.name, e)
        return {}
    except Exception as e:
        log.warning("Claude extraction failed for %s: %s", file_path.name, e)
        return {}


def apply_extraction(record: BillRecord, extracted: dict, fleet_lookup: dict) -> None:
    """Map Claude extraction result onto a BillRecord, then cross-check with Alvys."""
    record.vendor = (extracted.get("vendor") or "").strip()
    record.invoice_number = (extracted.get("invoice_number") or "").strip()
    record.invoice_date = (extracted.get("invoice_date") or "").strip()
    record.due_date = (extracted.get("due_date") or "").strip()
    record.expiration_date = (extracted.get("expiration_date") or "").strip()
    record.bill_type = (extracted.get("bill_type") or "").strip()
    record.service_description = (extracted.get("service_description") or "")[:200]
    record.confidence = extracted.get("confidence", "Low")
    record.unit_number = (extracted.get("unit_number") or "").strip()
    record.equipment_type = (extracted.get("equipment_type") or "").strip()

    raw_amount = extracted.get("amount")
    if raw_amount is not None:
        try:
            record.amount = float(str(raw_amount).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass

    # Map bill_to → canonical operating company
    bill_to_raw = (extracted.get("bill_to") or "Unknown").strip()
    record.operating_company = _map_company(bill_to_raw)

    # Alvys cross-check: if we have a unit number and Alvys lookup, validate
    unit = record.unit_number
    if unit and unit.upper() != "FLEET" and fleet_lookup:
        fleet_info = fleet_lookup.get(unit)
        if fleet_info:
            # If Claude's company differs from fleet lookup, log but trust Claude
            # (bill-to address on the invoice is the authoritative source)
            if fleet_info["company"] != record.operating_company:
                log.debug(
                    "  Unit %s: Alvys says %s, bill says %s — keeping bill value",
                    unit,
                    fleet_info["company"],
                    record.operating_company,
                )
            # Fill equipment_type from Alvys if Claude didn't get it
            if not record.equipment_type:
                record.equipment_type = fleet_info["equipment_type"]
        else:
            log.debug("  Unit %s not found in Alvys fleet lookup", unit)


def _map_company(raw: str) -> str:
    low = raw.lower()
    if any(x in low for x in ("x-trux", "xtrux", "x trux")):
        return "X-Trux"
    if any(x in low for x in ("x-linx", "xlinx", "x linx")):
        return "X-Linx"
    if any(x in low for x in ("truk-way", "trukway", "truk way")):
        return "Truk-Way"
    return ""  # blank → triggers Archive-Needs-Review


# ------------------------------------------------------------------
# Per-file worker
# ------------------------------------------------------------------
def process_one(
    pdf_path: Path,
    manifest: dict,
    fleet_lookup: dict,
    sp_client,            # BillsInboxClient | None (None = dry run)
    dry_run: bool,
) -> BillRecord:
    record = BillRecord(
        file_path=pdf_path,
        source_file=pdf_path.name,
    )

    # Hash
    record.file_hash = _sha256(pdf_path)

    # Skip if already processed
    if record.file_hash in manifest.get("processed", {}):
        prior = manifest["processed"][record.file_hash]
        record.status = prior.get("status", "Archived")
        record.item_id = prior.get("item_id", "")
        record.error = "SKIPPED (already in manifest)"
        return record

    # Extract
    extracted = extract_with_claude(pdf_path)
    apply_extraction(record, extracted, fleet_lookup)
    record.validate()

    # Determine SharePoint folder — fall back to Unknown/{year} if company missing
    year = _year_from(record.invoice_date) or datetime.now().year
    company_folder = record.operating_company if record.operating_company in COMPANIES else "Unknown"
    record.sharepoint_folder = f"{company_folder}/{year}"

    if dry_run:
        record.error = "DRY-RUN (not uploaded)"
        return record

    # Upload
    try:
        sp_client.ensure_folder(record.sharepoint_folder)
        record.item_id = sp_client.upload_pdf(
            folder_path=record.sharepoint_folder,
            filename=pdf_path.name,
            file_path=pdf_path,
        )
    except Exception as e:
        record.error = f"UPLOAD_FAILED: {e}"
        log.error("Upload failed for %s: %s", pdf_path.name, e)
        return record

    # Set metadata
    sp_fields = record.to_sp_fields()
    if sp_fields and record.item_id:
        ok = sp_client.set_metadata(record.item_id, sp_fields)
        if not ok:
            record.error = "METADATA_FAILED (file uploaded, columns not set)"

    return record


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _year_from(date_str: str) -> int | None:
    if date_str and len(date_str) >= 4:
        try:
            return int(date_str[:4])
        except ValueError:
            pass
    return None


# ------------------------------------------------------------------
# Summary + CSV report
# ------------------------------------------------------------------
def print_summary(results: list[BillRecord], log_dir: Path, dry_run: bool) -> None:
    archived = [r for r in results if r.status == "Archived" and not r.error.startswith("SKIPPED")]
    needs_review = [r for r in results if r.status == "Archive-Needs-Review"]
    skipped = [r for r in results if r.error.startswith("SKIPPED")]
    failed = [r for r in results if r.error and not r.error.startswith(("SKIPPED", "DRY-RUN", "METADATA"))]

    missing_counts: dict[str, int] = {}
    for r in needs_review:
        for f_name in r.missing_fields:
            missing_counts[f_name] = missing_counts.get(f_name, 0) + 1

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode = " [DRY-RUN]" if dry_run else ""
    lines = [
        "=" * 62,
        f"Bill Archive Complete — {stamp}{mode}",
        "=" * 62,
        f"Total PDFs found:          {len(results):>6,}",
        f"Already processed (skip):  {len(skipped):>6,}",
        f"Processed this run:        {len(results) - len(skipped):>6,}",
        f"  ✓ Archived:              {len(archived):>6,}",
        f"  ⚠ Archive-Needs-Review:  {len(needs_review):>6,}",
        f"  ✗ Failed:                {len(failed):>6,}",
    ]
    if missing_counts:
        lines += ["", "Missing field breakdown (Needs-Review bills):"]
        for fname, cnt in sorted(missing_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {fname:<22} {cnt:>5,} bills")

    for line in lines:
        log.info(line)

    # Write needs-review CSV
    if needs_review:
        today = datetime.now().strftime("%Y-%m-%d")
        csv_path = log_dir / f"bill_archive_needs_review_{today}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "File", "Missing_Fields", "Vendor", "Amount", "InvoiceDate",
                "OperatingCompany", "UnitNumber", "BillType", "Confidence",
                "SharePoint_Folder", "ItemID",
            ])
            writer.writeheader()
            for r in needs_review:
                writer.writerow({
                    "File": r.source_file,
                    "Missing_Fields": r.missing_fields_str,
                    "Vendor": r.vendor,
                    "Amount": r.amount or "",
                    "InvoiceDate": r.invoice_date,
                    "OperatingCompany": r.operating_company,
                    "UnitNumber": r.unit_number,
                    "BillType": r.bill_type,
                    "Confidence": r.confidence,
                    "SharePoint_Folder": r.sharepoint_folder,
                    "ItemID": r.item_id,
                })
        log.info("")
        log.info("Review queue saved: %s", csv_path)
    log.info("=" * 62)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive historical bills into SharePoint Bills Inbox"
    )
    parser.add_argument(
        "--source", required=True,
        help="Folder containing historical PDF bills (scanned recursively)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Extract and validate but do not upload to SharePoint"
    )
    parser.add_argument(
        "--workers", type=int, default=4,
        help="Parallel upload workers (default 4)"
    )
    parser.add_argument(
        "--manifest", default="",
        help="Path to checkpoint manifest JSON (default: output/bill_archive_manifest.json)"
    )
    args = parser.parse_args()

    load_dotenv()
    log_dir = Path(os.environ.get("ARCHIVE_LOG_DIR", "output"))
    log_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"bill_archive_{today}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    source_dir = Path(args.source)
    if not source_dir.is_dir():
        log.error("Source folder not found: %s", source_dir)
        sys.exit(1)

    manifest_path = Path(
        args.manifest
        or os.environ.get("ARCHIVE_MANIFEST_PATH", "output/bill_archive_manifest.json")
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    # Discover PDFs
    pdf_files = sorted(source_dir.rglob("*.pdf")) + sorted(source_dir.rglob("*.PDF"))
    # deduplicate (rglob on case-insensitive fs may double-count)
    seen_paths: set[Path] = set()
    unique_pdfs: list[Path] = []
    for p in pdf_files:
        rp = p.resolve()
        if rp not in seen_paths:
            seen_paths.add(rp)
            unique_pdfs.append(p)

    log.info("Source folder: %s", source_dir)
    log.info("PDFs found:    %d", len(unique_pdfs))

    manifest = load_manifest(manifest_path)
    already_done = sum(
        1 for p in unique_pdfs if _sha256(p) in manifest.get("processed", {})
    )
    log.info("Already in manifest (will skip): %d", already_done)
    log.info("To process this run: %d", len(unique_pdfs) - already_done)

    if not unique_pdfs:
        log.info("No PDFs found. Exiting.")
        return

    # Fleet lookup
    fleet_lookup = build_fleet_lookup()

    # SharePoint client
    sp_client = None
    if not args.dry_run:
        from src.onedrive_upload import get_token
        from src.bill_archive_sharepoint import BillsInboxClient

        tenant = os.environ.get("AZURE_TENANT_ID", "")
        app_id = os.environ.get("AZURE_CLIENT_ID", "")
        secret = os.environ.get("AZURE_CLIENT_SECRET", "")
        if not all([tenant, app_id, secret]):
            log.error("AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET not set")
            sys.exit(1)

        token = get_token(tenant, app_id, secret)
        site_host = os.environ.get("BILLS_INBOX_SITE_HOST", "xfreightnet.sharepoint.com")
        library = os.environ.get("BILLS_INBOX_LIBRARY", "Bills Inbox")
        sp_client = BillsInboxClient(token, site_host, library)
        sp_client.discover()

    # Process in parallel
    results: list[BillRecord] = []
    lock = threading.Lock()

    def _work(pdf_path: Path) -> BillRecord:
        r = process_one(pdf_path, manifest, fleet_lookup, sp_client, args.dry_run)
        if not r.error.startswith("SKIPPED") and not args.dry_run:
            save_manifest_entry(manifest_path, manifest, r)
        with lock:
            status_icon = {"Archived": "✓", "Archive-Needs-Review": "⚠"}.get(r.status, "✗")
            tag = f" [{r.error}]" if r.error else ""
            log.info("%s %-45s %s%s",
                     status_icon, pdf_path.name[:45], r.operating_company or "?", tag)
        return r

    log.info("=" * 62)
    log.info("Starting archive run — %d workers", args.workers)
    log.info("=" * 62)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_work, p): p for p in unique_pdfs}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                pdf = futures[fut]
                log.error("Worker exception for %s: %s", pdf.name, e)
                r = BillRecord(file_path=pdf, source_file=pdf.name,
                               status="Archive-Needs-Review", error=str(e))
                results.append(r)

    print_summary(results, log_dir, args.dry_run)


if __name__ == "__main__":
    main()
