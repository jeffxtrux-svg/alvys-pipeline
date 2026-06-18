"""Re-post Teams accountability cards with up-to-date ✅ marks.

Reads today's accountability JSON (written by the 5am safety brief run) from
OneDrive and today's entries from Accountability Log.xlsx, then re-posts the
per-owner Adaptive Cards with ✅ Actioned on items logged today.

No email is sent and no report is re-generated.

GitHub Secrets used:
  TEAMS_SAFETY_WEBHOOK
  TEAMS_FORM_URL        (optional)
  AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
  ONEDRIVE_USER_UPN
"""
from __future__ import annotations

import datetime
import io
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import json

from src.onedrive_upload import download_file, get_token
from src.suppression_registry import (
    load_registry, save_registry, prune,
    apply_resolved_to_registry,
)
from src.teams_adaptive_cards import post_adaptive_cards

_ACC_FOLDER = "Safety"


def _load_resolved_today(tok: str, upn: str, today: datetime.date) -> set[str]:
    """Return suppression tokens from Accountability Log.xlsx for today.

    Returns a flat set of:
      - Lowercased category names (when category is not "other")
      - "driver:<name>" tokens for every Driver/Unit logged today

    Matches items by category OR driver name so suppression works even when
    the form's Category field shows "Other" (pre-fill choice mismatch).
    """
    resolved: set[str] = set()
    try:
        raw = download_file(tok, upn, f"{_ACC_FOLDER}/Accountability Log.xlsx")
        xl  = pd.ExcelFile(io.BytesIO(raw))
        df  = xl.parse(xl.sheet_names[0])
        df.columns = [str(c).strip().lower() for c in df.columns]
        date_col = next((c for c in df.columns if "date" in c), None)
        cat_col  = next((c for c in df.columns if "category" in c), None)
        drv_col  = next((c for c in df.columns if "driver" in c or "unit" in c), None)
        if date_col is None:
            print("Accountability Log.xlsx: date column not found.")
            return resolved
        for _, row in df.iterrows():
            raw_date = row[date_col]
            if pd.isna(raw_date):
                continue
            try:
                row_date = pd.Timestamp(raw_date).date()
            except Exception:
                continue
            if row_date != today:
                continue
            if cat_col:
                cat = str(row[cat_col]).strip().lower()
                if cat and cat not in ("nan", "other"):
                    resolved.add(cat)
            if drv_col:
                drv = str(row[drv_col]).strip().lower()
                if drv and drv != "nan":
                    resolved.add(f"driver:{drv}")
    except Exception as exc:
        print(f"Could not read Accountability Log.xlsx: {exc}")
    return resolved


def main() -> int:
    webhook  = os.environ.get("TEAMS_SAFETY_WEBHOOK", "").strip()
    run_url  = os.environ.get("RUN_URL", "").strip()
    form_url = os.environ.get("TEAMS_FORM_URL", "").strip()

    tenant = os.environ.get("AZURE_TENANT_ID", "").strip()
    client = os.environ.get("AZURE_CLIENT_ID", "").strip()
    secret = os.environ.get("AZURE_CLIENT_SECRET", "").strip()
    upn    = os.environ.get("ONEDRIVE_USER_UPN", "").strip()

    if not all([tenant, client, secret, upn]):
        print("Missing Azure credentials — cannot load OneDrive data.")
        return 1

    tok   = get_token(tenant, client, secret)
    today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()

    # Find today's accountability JSON — prefer local, fall back to OneDrive.
    acc_path = Path(f"output/accountability-{today.isoformat()}.json")
    if not acc_path.exists():
        try:
            raw = download_file(
                tok, upn, f"{_ACC_FOLDER}/accountability-{today.isoformat()}.json"
            )
            acc_path.parent.mkdir(parents=True, exist_ok=True)
            acc_path.write_bytes(raw)
            print(f"Downloaded accountability JSON for {today} from OneDrive.")
        except Exception as exc:
            print(f"No accountability JSON found for {today}: {exc}")
            return 0

    resolved_today = _load_resolved_today(tok, upn, today)
    print(f"Actioned today: {sorted(resolved_today) or 'none'}")

    # Update suppression registry so tomorrow's brief skips newly actioned items.
    if resolved_today:
        try:
            acc_data   = json.loads(acc_path.read_bytes())
            all_items  = acc_data.get("audra", []) + acc_data.get("ops", [])
            registry   = load_registry(tok, upn)
            prune(registry, today)
            apply_resolved_to_registry(registry, resolved_today, all_items, today)
            save_registry(tok, upn, registry)
        except Exception as exc:
            print(f"Warning: could not update suppression registry: {exc}")

    post_adaptive_cards(acc_path, webhook, run_url, form_url,
                        resolved_today=resolved_today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
