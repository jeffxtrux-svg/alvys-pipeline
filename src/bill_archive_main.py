"""Bill Archive Tool — bulk-import historical PDFs into SharePoint Bills Inbox.

Scans a source folder (selected at run time via --source), extracts metadata
from each PDF using Claude, cross-checks unit numbers against the Alvys fleet,
and uploads every bill into Bills Inbox/{OperatingCompany}/{Year}/ with full
column metadata so they are searchable in SharePoint.

MODES
-----
    # 1) One-time setup — create all SharePoint columns automatically
    python -m src.bill_archive_main --setup-columns

    # 2) Verify every connection before the real run
    python -m src.bill_archive_main --test

    # 3) Dry run — extract + validate, no uploads (free check)
    python -m src.bill_archive_main --source /path/to/bills --dry-run

    # 4) Real archive run (resumes automatically after failures)
    python -m src.bill_archive_main --source /path/to/bills

    # Optional: reduce workers (default 4, ~50 min per 3,000 bills)
    python -m src.bill_archive_main --source /path/to/bills --workers 2

ARCHIVE MODE RULES
------------------
Status = "Archived"              when all 5 required fields are present:
                                   Vendor, Amount, InvoiceDate,
                                   OperatingCompany, UnitNumber (or "FLEET")
Status = "Archive-Needs-Review"  when any required field is missing —
                                   bill uploads to SharePoint but stays in the
                                   review queue (CSV report) for manual completion

ENVIRONMENT VARIABLES
---------------------
    # Azure (same app as OneDrive uploads — add Sites.Manage.All for --setup-columns)
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
    # Claude extraction
    ANTHROPIC_API_KEY
    # Alvys fleet lookup (optional — skipped if absent)
    ALVYS_CLIENT_ID, ALVYS_CLIENT_SECRET
    # SharePoint target (defaults shown)
    BILLS_INBOX_SITE_HOST=xfreightnet.sharepoint.com
    BILLS_INBOX_LIBRARY=Bills Inbox
    # Output paths (defaults shown)
    ARCHIVE_MANIFEST_PATH=output/bill_archive_manifest.json
    ARCHIVE_LOG_DIR=output
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
# Constants
# ------------------------------------------------------------------
REQUIRED_FIELDS = ("vendor", "amount", "invoice_date", "operating_company", "unit_number")
COMPANIES = {"X-Trux", "X-Linx", "Truk-Way"}

FLEET_TO_COMPANY: dict[str, str] = {
    "truk-way leasing llc": "Truk-Way",
    "truk-way leasing":     "Truk-Way",
    "cds express":          "X-Trux",
    "owner ops":            "X-Trux",
    "x-trux":               "X-Trux",
    "x-linx":               "X-Linx",
}

# SharePoint internal column name → BillRecord field name
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
    file_path: Path = field(default=None)
    file_hash: str = ""
    source_file: str = ""
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
    status: str = "Archive-Needs-Review"
    archive_mode: bool = True
    missing_fields: list = field(default_factory=list)
    missing_fields_str: str = ""
    sharepoint_folder: str = ""
    item_id: str = ""
    error: str = ""

    def validate(self) -> None:
        self.missing_fields = []
        for f_name in REQUIRED_FIELDS:
            val = getattr(self, f_name, None)
            if not val and val != 0:
                self.missing_fields.append(f_name)
        self.missing_fields_str = ", ".join(self.missing_fields)
        self.status = "Archived" if not self.missing_fields else "Archive-Needs-Review"

    def to_sp_fields(self) -> dict:
        data = asdict(self)
        fields: dict = {}
        for sp_col, rec_field in SP_COLUMN_MAP.items():
            val = data.get(rec_field)
            if val is None or val == "" or val == []:
                continue
            if rec_field == "amount" and isinstance(val, float):
                val = round(val, 2)
            fields[sp_col] = val
        return fields


# ------------------------------------------------------------------
# Manifest
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
            "file":         record.source_file,
            "status":       record.status,
            "item_id":      record.item_id,
            "folder":       record.sharepoint_folder,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(manifest, indent=2))


# ------------------------------------------------------------------
# Alvys fleet lookup (optional)
# ------------------------------------------------------------------
def build_fleet_lookup() -> dict[str, dict]:
    client_id     = os.environ.get("ALVYS_CLIENT_ID", "")
    client_secret = os.environ.get("ALVYS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.info("Alvys creds not set — fleet cross-check disabled")
        return {}
    try:
        from src.alvys_client import AlvysClient
        client = AlvysClient(client_id, client_secret)
        lookup: dict[str, dict] = {}

        for t in client.fetch_trucks():
            num = _try_keys(t, ["TruckNum", "TruckNumber", "Number", "Name"])
            if not num:
                continue
            fleet_val = _try_keys(t, ["Fleet", "FleetName"])
            if isinstance(fleet_val, dict):
                fleet_raw = (fleet_val.get("name") or fleet_val.get("Name") or "").lower().strip()
            else:
                fleet_raw = str(fleet_val).lower().strip() if fleet_val else ""
            company   = FLEET_TO_COMPANY.get(fleet_raw, "X-Trux")
            lookup[str(num).strip()] = {"company": company, "equipment_type": "Tractor"}

        for t in client.fetch_trailers():
            num = _try_keys(t, ["TrailerNum", "TrailerNumber", "Number", "Name"])
            if not num:
                continue
            lookup[str(num).strip()] = {"company": "X-Trux", "equipment_type": "Trailer"}

        log.info("Alvys fleet lookup: %d units loaded", len(lookup))
        return lookup
    except Exception as e:
        log.warning("Alvys fleet lookup failed (%s) — continuing without it", e)
        return {}


def _try_keys(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k]:
            return d[k]
    return None


# ------------------------------------------------------------------
# Claude extraction
# ------------------------------------------------------------------
_EXTRACTION_PROMPT = """You are an AP bill/invoice data extractor for XFreight, a trucking company.
Extract structured data from this bill or invoice PDF.

COMPANY IDENTIFICATION — the "Bill To" company will be one of:
- X-Trux  (X-TRUX INC, X-TRUX Inc, X-Trux Inc) — the trucking carrier
- X-Linx  (X-LINX INC, X-Linx Inc)              — the freight brokerage
- Truk-Way (TRUK-WAY LEASING LLC, Truk-Way Leasing) — equipment leasing entity

UNIT NUMBERS — look carefully in ALL line items, work order lines, and asset fields:
- Truck unit numbers:   5-digit (e.g. 41182, 42186, 43199)
- Trailer unit numbers: 3-digit (e.g. 246, 247, 248)
- Format in service invoices: often appears as "248 CPT" where 248 is the unit# and CPT is a tech code
- For company-wide bills (fleet insurance, permits) with no specific unit: use "FLEET"

BILL TYPES — pick the single best match:
DOT Inspection | PM Inspection | Maintenance & Repairs | Parts | Tires | Fuel |
Insurance | Registration | Permits | Tolls | Drug Testing | Driver Medical |
Trailer Rental | Office/Admin | Other

EQUIPMENT TYPE:
- 3-digit unit → Trailer
- 5-digit unit → Tractor
- FLEET or no unit → Fleet/None

Return ONLY a valid JSON object, no other text:
{
  "vendor": "exact vendor name from bill header, or null",
  "bill_to": "X-Trux" | "X-Linx" | "Truk-Way" | "Unknown",
  "invoice_number": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "amount": total amount as number (no $ or commas) or null,
  "unit_number": "unit number string, FLEET, or null",
  "equipment_type": "Tractor" | "Trailer" | "Fleet/None" | null,
  "bill_type": "one of the listed types or null",
  "service_description": "brief work description max 200 chars, or null",
  "expiration_date": "YYYY-MM-DD policy end date for insurance/registration, or null",
  "confidence": "High" | "Medium" | "Low"
}

confidence = High   all key fields (vendor, bill_to, invoice_date, amount) clearly present
confidence = Medium most fields present, one or more inferred
confidence = Low    document unclear, scanned poorly, or major fields missing"""


def extract_with_claude(file_path: Path) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    pdf_b64 = base64.standard_b64encode(file_path.read_bytes()).decode()
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{
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
            }],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except json.JSONDecodeError as e:
        log.warning("Non-JSON from Claude for %s: %s", file_path.name, e)
        return {}
    except Exception as e:
        log.warning("Claude extraction failed for %s: %s", file_path.name, e)
        return {}


def apply_extraction(record: BillRecord, extracted: dict, fleet_lookup: dict) -> None:
    record.vendor              = (extracted.get("vendor") or "").strip()
    record.invoice_number      = (extracted.get("invoice_number") or "").strip()
    record.invoice_date        = (extracted.get("invoice_date") or "").strip()
    record.due_date            = (extracted.get("due_date") or "").strip()
    record.expiration_date     = (extracted.get("expiration_date") or "").strip()
    record.bill_type           = (extracted.get("bill_type") or "").strip()
    record.service_description = (extracted.get("service_description") or "")[:200]
    record.confidence          = extracted.get("confidence", "Low")
    record.unit_number         = (extracted.get("unit_number") or "").strip()
    record.equipment_type      = (extracted.get("equipment_type") or "").strip()

    raw_amount = extracted.get("amount")
    if raw_amount is not None:
        try:
            record.amount = float(str(raw_amount).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass

    record.operating_company = _map_company(extracted.get("bill_to") or "")

    # Alvys cross-check: fill equipment_type if Claude missed it
    unit = record.unit_number
    if unit and unit.upper() != "FLEET" and fleet_lookup:
        info = fleet_lookup.get(unit)
        if info:
            if not record.equipment_type:
                record.equipment_type = info["equipment_type"]
            if record.operating_company != info["company"]:
                log.debug("Unit %s: Alvys=%s bill=%s — keeping bill value",
                          unit, info["company"], record.operating_company)


def _map_company(raw: str) -> str:
    low = raw.lower()
    if any(x in low for x in ("x-trux", "xtrux", "x trux")):
        return "X-Trux"
    if any(x in low for x in ("x-linx", "xlinx", "x linx")):
        return "X-Linx"
    if any(x in low for x in ("truk-way", "trukway", "truk way")):
        return "Truk-Way"
    return ""


# ------------------------------------------------------------------
# Per-file worker
# ------------------------------------------------------------------
def process_one(
    pdf_path: Path,
    manifest: dict,
    fleet_lookup: dict,
    sp_client,
    dry_run: bool,
) -> BillRecord:
    record = BillRecord(file_path=pdf_path, source_file=pdf_path.name)
    record.file_hash = _sha256(pdf_path)

    if record.file_hash in manifest.get("processed", {}):
        prior = manifest["processed"][record.file_hash]
        record.status    = prior.get("status", "Archived")
        record.item_id   = prior.get("item_id", "")
        record.error     = "SKIPPED"
        return record

    extracted = extract_with_claude(pdf_path)
    apply_extraction(record, extracted, fleet_lookup)
    record.validate()

    year           = _year_from(record.invoice_date) or datetime.now().year
    company_folder = record.operating_company if record.operating_company in COMPANIES else "Unknown"
    record.sharepoint_folder = f"{company_folder}/{year}"

    if dry_run:
        record.error = "DRY-RUN"
        return record

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

    if record.item_id:
        sp_fields = record.to_sp_fields()
        if sp_fields:
            ok = sp_client.set_metadata(record.item_id, sp_fields)
            if not ok:
                record.error = "METADATA_FAILED"

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
# Summary + CSV
# ------------------------------------------------------------------
def print_summary(results: list[BillRecord], log_dir: Path, dry_run: bool) -> None:
    archived     = [r for r in results if r.status == "Archived"              and r.error not in ("SKIPPED", "DRY-RUN")]
    needs_review = [r for r in results if r.status == "Archive-Needs-Review"]
    skipped      = [r for r in results if r.error == "SKIPPED"]
    failed       = [r for r in results if r.error and r.error not in ("SKIPPED", "DRY-RUN", "METADATA_FAILED")]

    missing_counts: dict[str, int] = {}
    for r in needs_review:
        for f_name in r.missing_fields:
            missing_counts[f_name] = missing_counts.get(f_name, 0) + 1

    mode = " [DRY-RUN]" if dry_run else ""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 62,
        f"Bill Archive Complete — {stamp}{mode}",
        "=" * 62,
        f"  Total PDFs found           {len(results):>6,}",
        f"  Already processed (skip)   {len(skipped):>6,}",
        f"  Processed this run         {len(results) - len(skipped):>6,}",
        f"    ✓  Archived              {len(archived):>6,}",
        f"    ⚠  Archive-Needs-Review  {len(needs_review):>6,}",
        f"    ✗  Failed                {len(failed):>6,}",
    ]
    if missing_counts:
        lines += ["", "  Missing fields (Needs-Review bills):"]
        for fname, cnt in sorted(missing_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    {fname:<22} {cnt:>5,} bills")
    for line in lines:
        log.info(line)

    if needs_review:
        today    = datetime.now().strftime("%Y-%m-%d")
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
                    "File":             r.source_file,
                    "Missing_Fields":   r.missing_fields_str,
                    "Vendor":           r.vendor,
                    "Amount":           r.amount or "",
                    "InvoiceDate":      r.invoice_date,
                    "OperatingCompany": r.operating_company,
                    "UnitNumber":       r.unit_number,
                    "BillType":         r.bill_type,
                    "Confidence":       r.confidence,
                    "SharePoint_Folder": r.sharepoint_folder,
                    "ItemID":           r.item_id,
                })
        log.info("")
        log.info("  Review queue → %s", csv_path)
    log.info("=" * 62)


# ------------------------------------------------------------------
# --setup-columns mode
# ------------------------------------------------------------------
def run_setup_columns(sp_client) -> None:
    log.info("=" * 62)
    log.info("Setting up Bills Inbox columns")
    log.info("=" * 62)
    try:
        created, skipped = sp_client.setup_columns()
        log.info("")
        log.info("  Created : %d columns", created)
        log.info("  Skipped : %d (already existed)", skipped)
        log.info("")
        log.info("✓ Column setup complete. Run --test to verify, then --dry-run.")
    except Exception as e:
        log.error("Column setup failed: %s", e)
        log.error("")
        log.error("If you see a 403 Forbidden error, the Azure app needs")
        log.error("Sites.Manage.All permission (in addition to Sites.ReadWrite.All).")
        log.error("Add it in Azure portal → App registrations → API permissions.")
        sys.exit(1)
    log.info("=" * 62)


# ------------------------------------------------------------------
# --test mode
# ------------------------------------------------------------------
def run_test(sp_client) -> None:
    log.info("=" * 62)
    log.info("Connection test")
    log.info("=" * 62)
    all_ok = True

    # Azure + SharePoint
    log.info("")
    log.info("SharePoint Bills Inbox:")
    try:
        sp_client.discover()
        log.info("  ✓ Connected  (site + drive resolved)")
        cols = sp_client.list_existing_columns()
        required = set(SP_COLUMN_MAP.keys())
        found    = set(cols)
        missing  = required - found
        if missing:
            log.warning("  ⚠ Missing columns (run --setup-columns): %s",
                        ", ".join(sorted(missing)))
            all_ok = False
        else:
            log.info("  ✓ All %d required columns present", len(required))
    except Exception as e:
        log.error("  ✗ FAILED: %s", e)
        all_ok = False

    # Claude
    log.info("")
    log.info("Claude (Anthropic API):")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        log.error("  ✗ ANTHROPIC_API_KEY not set")
        all_ok = False
    else:
        try:
            import anthropic
            client = anthropic.Anthropic()
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            log.info("  ✓ Connected  (model: claude-haiku-4-5-20251001)")
        except Exception as e:
            log.error("  ✗ FAILED: %s", e)
            all_ok = False

    # Alvys (optional)
    log.info("")
    log.info("Alvys fleet lookup (optional):")
    if os.environ.get("ALVYS_CLIENT_ID") and os.environ.get("ALVYS_CLIENT_SECRET"):
        try:
            lookup = build_fleet_lookup()
            log.info("  ✓ Connected  (%d fleet units loaded)", len(lookup))
        except Exception as e:
            log.warning("  ⚠ Failed (%s) — archive will run without fleet cross-check", e)
    else:
        log.info("  — Not configured (ALVYS_CLIENT_ID not set) — skipped")

    log.info("")
    if all_ok:
        log.info("✓ All checks passed. Ready to run --dry-run then the real archive.")
    else:
        log.info("✗ One or more checks failed — fix above issues before running.")
    log.info("=" * 62)
    if not all_ok:
        sys.exit(1)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def _make_sp_client(token_fn=None):
    """Build and return a discovered BillsInboxClient."""
    from src.onedrive_upload import get_token
    from src.bill_archive_sharepoint import BillsInboxClient

    tenant = os.environ.get("AZURE_TENANT_ID", "")
    app_id = os.environ.get("AZURE_CLIENT_ID", "")
    secret = os.environ.get("AZURE_CLIENT_SECRET", "")
    if not all([tenant, app_id, secret]):
        log.error("AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET not set in .env")
        sys.exit(1)

    token     = get_token(tenant, app_id, secret)
    site_host = os.environ.get("BILLS_INBOX_SITE_HOST", "xfreightnet.sharepoint.com")
    library   = os.environ.get("BILLS_INBOX_LIBRARY",   "Bills Inbox")
    return BillsInboxClient(token, site_host, library)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bill archive tool — import historical PDFs into SharePoint Bills Inbox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.bill_archive_main --setup-columns
  python -m src.bill_archive_main --test
  python -m src.bill_archive_main --source /path/to/bills --dry-run
  python -m src.bill_archive_main --source /path/to/bills
        """,
    )
    parser.add_argument("--source",        help="Folder of PDF bills to archive (scanned recursively)")
    parser.add_argument("--setup-columns", action="store_true",
                        help="Auto-create all required SharePoint columns and exit")
    parser.add_argument("--test",          action="store_true",
                        help="Verify all connections and column setup then exit")
    parser.add_argument("--dry-run",       action="store_true",
                        help="Extract + validate without uploading to SharePoint")
    parser.add_argument("--workers",       type=int, default=4,
                        help="Parallel workers (default 4)")
    parser.add_argument("--manifest",      default="",
                        help="Checkpoint manifest path (default: output/bill_archive_manifest.json)")
    args = parser.parse_args()

    load_dotenv()

    log_dir = Path(os.environ.get("ARCHIVE_LOG_DIR", "output"))
    log_dir.mkdir(parents=True, exist_ok=True)
    today    = datetime.now().strftime("%Y-%m-%d")
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

    # ---- Setup-columns mode ----
    if args.setup_columns:
        sp = _make_sp_client()
        sp.discover()
        run_setup_columns(sp)
        return

    # ---- Test mode ----
    if args.test:
        sp = _make_sp_client()
        run_test(sp)
        return

    # ---- Archive run ----
    if not args.source:
        parser.error("--source is required for an archive run (or use --setup-columns / --test)")

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
    seen_paths: set[Path] = set()
    unique_pdfs: list[Path] = []
    for p in sorted(source_dir.rglob("*.pdf")) + sorted(source_dir.rglob("*.PDF")):
        rp = p.resolve()
        if rp not in seen_paths:
            seen_paths.add(rp)
            unique_pdfs.append(p)

    manifest     = load_manifest(manifest_path)
    already_done = sum(1 for p in unique_pdfs if _sha256(p) in manifest.get("processed", {}))

    log.info("=" * 62)
    log.info("Bill Archive — %s%s", today, " [DRY-RUN]" if args.dry_run else "")
    log.info("  Source   : %s", source_dir)
    log.info("  PDFs     : %d found  |  %d already done  |  %d to process",
             len(unique_pdfs), already_done, len(unique_pdfs) - already_done)
    log.info("  Workers  : %d", args.workers)
    log.info("=" * 62)

    if not unique_pdfs:
        log.info("No PDFs found in %s", source_dir)
        return

    fleet_lookup = build_fleet_lookup()

    sp_client = None
    if not args.dry_run:
        sp_client = _make_sp_client()
        sp_client.discover()

    results: list[BillRecord] = []
    lock = threading.Lock()

    def _work(pdf_path: Path) -> BillRecord:
        r = process_one(pdf_path, manifest, fleet_lookup, sp_client, args.dry_run)
        if r.error not in ("SKIPPED", "DRY-RUN") and not args.dry_run:
            save_manifest_entry(manifest_path, manifest, r)
        with lock:
            icon = {"Archived": "✓", "Archive-Needs-Review": "⚠"}.get(r.status, "✗")
            tag  = f"  [{r.error}]" if r.error and r.error != "SKIPPED" else ""
            log.info("%s  %-50s  %s%s",
                     icon, pdf_path.name[:50],
                     r.operating_company or "?", tag)
        return r

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_work, p): p for p in unique_pdfs}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                pdf = futures[fut]
                log.error("Worker error for %s: %s", pdf.name, e)
                results.append(BillRecord(
                    file_path=pdf, source_file=pdf.name,
                    status="Archive-Needs-Review", error=str(e),
                ))

    print_summary(results, log_dir, args.dry_run)


if __name__ == "__main__":
    main()
