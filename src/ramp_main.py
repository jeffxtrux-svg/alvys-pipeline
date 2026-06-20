"""Ramp data pull — writes Ramp_Master.xlsx to OneDrive/Ramp/.

Sheets:
    Bills         — AP bills (vendor invoices) by status
    Transactions  — card transactions YTD
    Users         — cardholders + roles

Required env / GitHub Secrets:
    RAMP_CLIENT_ID       — Ramp Developer app client ID
    RAMP_CLIENT_SECRET   — Ramp Developer app client secret
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from .onedrive_upload import ensure_folder, get_token, upload_file
from .ramp_client import RampClient

log = logging.getLogger("ramp_main")


# ── field normalisers ─────────────────────────────────────────────────────────

def _bills_df(rows: list[dict]) -> pd.DataFrame:
    records = []
    for b in rows:
        vendor    = b.get("vendor") or {}
        amount    = b.get("amount") or {}
        records.append({
            "BillId":          b.get("id"),
            "VendorName":      vendor.get("name"),
            "VendorId":        vendor.get("id"),
            "InvoiceNumber":   b.get("invoice_number"),
            "InvoiceDate":     b.get("invoice_date"),
            "DueDate":         b.get("due_date"),
            "AmountTotal":     _cents_to_dollars(amount.get("amount")),
            "AmountCurrency":  amount.get("currency_code", "USD"),
            "PaymentStatus":   b.get("payment_status"),
            "ApprovalStatus":  b.get("approval_status"),
            "CreatedAt":       b.get("created_at", "")[:10],
            "PaidAt":          (b.get("paid_at") or "")[:10],
            "Memo":            b.get("memo"),
        })
    df = pd.DataFrame(records)
    if not df.empty:
        for col in ("InvoiceDate", "DueDate", "CreatedAt", "PaidAt"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def _transactions_df(rows: list[dict]) -> pd.DataFrame:
    records = []
    for t in rows:
        holder   = t.get("card_holder") or {}
        merchant = t.get("merchant") or {}
        receipts = t.get("receipts") or []
        records.append({
            "TransactionId":    t.get("id"),
            "CardholderName":   holder.get("name"),
            "CardholderEmail":  holder.get("email"),
            "MerchantName":     merchant.get("name"),
            "MerchantCategory": merchant.get("category_code"),
            "Amount":           _cents_to_dollars(t.get("amount")),
            "CurrencyCode":     t.get("currency_code", "USD"),
            "TransactionDate":  (t.get("user_transaction_time") or "")[:10],
            "State":            t.get("state"),
            "ReceiptMissing":   len(receipts) == 0,
            "PolicyViolation":  bool(t.get("policy_violations")),
            "Memo":             t.get("memo"),
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df["TransactionDate"] = pd.to_datetime(df["TransactionDate"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def _users_df(rows: list[dict]) -> pd.DataFrame:
    records = []
    for u in rows:
        records.append({
            "UserId":       u.get("id"),
            "FirstName":    u.get("first_name"),
            "LastName":     u.get("last_name"),
            "Email":        u.get("email"),
            "Role":         u.get("role"),
            "Status":       u.get("status"),
            "DepartmentId": u.get("department_id"),
            "ManagerId":    u.get("manager_id"),
        })
    return pd.DataFrame(records)


def _cents_to_dollars(value: Any) -> float | None:
    """Ramp returns amounts in cents as integers."""
    if value is None:
        return None
    try:
        return int(value) / 100
    except (ValueError, TypeError):
        return None


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    client_id     = os.environ.get("RAMP_CLIENT_ID", "")
    client_secret = os.environ.get("RAMP_CLIENT_SECRET", "")
    az_tenant     = os.environ.get("AZURE_TENANT_ID", "")
    az_client     = os.environ.get("AZURE_CLIENT_ID", "")
    az_secret     = os.environ.get("AZURE_CLIENT_SECRET", "")
    upn           = os.environ.get("ONEDRIVE_USER_UPN", "")

    missing = [k for k, v in {
        "RAMP_CLIENT_ID": client_id,
        "RAMP_CLIENT_SECRET": client_secret,
        "AZURE_TENANT_ID": az_tenant,
        "AZURE_CLIENT_ID": az_client,
        "AZURE_CLIENT_SECRET": az_secret,
        "ONEDRIVE_USER_UPN": upn,
    }.items() if not v]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    # Pull YTD by default
    from_date = str(datetime.date.today().replace(month=1, day=1))

    ramp = RampClient(client_id, client_secret)

    log.info("Pulling Ramp bills (from %s)…", from_date)
    bills = ramp.bills(from_date=from_date)
    bills_df = _bills_df(bills)
    log.info("  %d bills", len(bills_df))

    log.info("Pulling Ramp card transactions (from %s)…", from_date)
    try:
        txns = ramp.transactions(from_date=from_date)
        txns_df = _transactions_df(txns)
        log.info("  %d transactions", len(txns_df))
    except Exception as exc:
        log.warning("  transactions skipped (%s) — enable transactions:read scope in Ramp Developer App", exc)
        txns_df = pd.DataFrame()

    log.info("Pulling Ramp users…")
    try:
        users_df = _users_df(ramp.users())
        log.info("  %d users", len(users_df))
    except Exception as exc:
        log.warning("  users skipped (%s) — enable users:read scope in Ramp Developer App", exc)
        users_df = pd.DataFrame()

    # Write Excel
    out_path = Path("output/ramp/Ramp_Master.xlsx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        bills_df.to_excel(writer, sheet_name="Bills", index=False)
        txns_df.to_excel(writer, sheet_name="Transactions", index=False)
        users_df.to_excel(writer, sheet_name="Users", index=False)
    log.info("Wrote %s", out_path)

    # Upload to OneDrive
    graph_token = get_token(az_tenant, az_client, az_secret)
    ensure_folder(graph_token, upn, "Ramp")
    upload_file(graph_token, upn, "Ramp/Ramp_Master.xlsx", out_path.read_bytes())
    log.info("Uploaded to OneDrive/Ramp/ ✓  bills=%d  txns=%d", len(bills_df), len(txns_df))


if __name__ == "__main__":
    main()
