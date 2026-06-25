"""Cross-source accounting reconciliation — Ramp AP vs QuickBooks AP.

Reads from OneDrive (QB and Ramp must have run first):
    QuickBooks/QB_AgedPayableDetail.xlsx  → open bills by vendor + aging bucket
    Ramp/Ramp_Master.xlsx                 → Bills sheet (all Ramp AP)

Produces Recon_Master.xlsx → OneDrive/Reconciliation/  with sheets:
    Summary        — flag counts + dollar totals at a glance
    AP_Not_In_QB   — Ramp bills not yet entered in QB (action list for Audra)
    AP_In_Both     — Ramp bills that DO match a QB entry (confirmation)
    QB_Only        — QB AP entries with no Ramp counterpart (manual bills)

Matching logic:
    1. Normalize vendor names (uppercase, strip punctuation, drop Inc/LLC/Corp suffixes)
    2. Try invoice-number match as a tiebreaker when vendor names collide
    A Ramp bill is "matched" when a QB row shares the same normalized vendor name.

Required env / GitHub Secrets (shared with other connectors):
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
"""
from __future__ import annotations

import datetime
import io
import logging
import os
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .onedrive_upload import ensure_folder, get_token, upload_file
from .onedrive_upload import download_file as _od_download

log = logging.getLogger("accounting_recon")

# ── tuneable thresholds ───────────────────────────────────────────────────────

AP_LAG_DAYS = int(os.environ.get("RECON_AP_LAG_DAYS", "3"))   # flag if bill > N days old in Ramp but absent from QB

# QB aging bucket ordering for the summary sort
_BUCKET_ORDER = {
    "Current":                    0,
    "1 - 30":                     1,
    "31 - 60":                    2,
    "61 - 90":                    3,
    "91 or more days past due":   4,
}


# ── vendor name normaliser ────────────────────────────────────────────────────

_STRIP_SUFFIXES = re.compile(
    r"\b(inc|llc|corp|co|ltd|company|enterprises|services|solutions|group|"
    r"incorporated|limited|l\.l\.c|l\.p|lp)\b\.?$",
    re.IGNORECASE,
)
_STRIP_PUNCT = re.compile(r"[^A-Z0-9 ]")


def _norm_vendor(name: str | None) -> str:
    if not name:
        return ""
    s = str(name).upper().strip()
    s = _STRIP_SUFFIXES.sub("", s).strip()
    s = _STRIP_PUNCT.sub("", s)
    return re.sub(r" +", " ", s).strip()


def _norm_inv(num: str | None) -> str:
    """Normalise invoice number — strip spaces, dashes, leading zeros."""
    if not num:
        return ""
    return re.sub(r"[\s\-]", "", str(num)).lstrip("0").upper()


# ── loaders ───────────────────────────────────────────────────────────────────

def _load_qb_ap(graph_token: str, upn: str) -> pd.DataFrame:
    try:
        raw = _od_download(graph_token, upn, "QuickBooks/QB_AgedPayableDetail.xlsx")
        df = pd.read_excel(io.BytesIO(raw))
        # Keep only unpaid bill rows (exclude payments, credits, subtotals)
        df = df[
            (df["Row_Type"] == "Data") &
            (df["Transaction Type"] == "Bill") &
            (pd.to_numeric(df["Open Balance"], errors="coerce").fillna(0) > 0)
        ].copy()
        df["VendorNorm"] = df["Vendor"].apply(_norm_vendor)
        df["NumNorm"]    = df["Num"].apply(_norm_inv)
        log.info("  QB AP: %d open bills across %d companies",
                 len(df), df["Company"].nunique() if "Company" in df.columns else 0)
        return df
    except Exception as exc:
        log.warning("Could not load QB AP: %s", exc)
        return pd.DataFrame()


def _load_ramp_bills(graph_token: str, upn: str) -> pd.DataFrame:
    try:
        raw = _od_download(graph_token, upn, "Ramp/Ramp_Master.xlsx")
        df = pd.read_excel(io.BytesIO(raw), sheet_name="Bills")
        # Exclude already-paid bills from the gap check
        paid_statuses = {"PAID", "paid", "CANCELED", "canceled", "CANCELLED"}
        df = df[~df["PaymentStatus"].isin(paid_statuses)].copy()
        df["VendorNorm"] = df["VendorName"].apply(_norm_vendor)
        df["NumNorm"]    = df["InvoiceNumber"].apply(_norm_inv)
        # Age in days since bill was created in Ramp
        df["CreatedAt"] = pd.to_datetime(df["CreatedAt"], errors="coerce")
        today = pd.Timestamp(datetime.date.today())
        df["AgeDays"] = (today - df["CreatedAt"]).dt.days.fillna(0).astype(int)
        log.info("  Ramp bills: %d unpaid", len(df))
        return df
    except Exception as exc:
        log.warning("Could not load Ramp bills: %s", exc)
        return pd.DataFrame()


# ── verification helpers ──────────────────────────────────────────────────────

def _word_overlap(a: str, b: str) -> int:
    """0-100 score: what % of the shorter name's words appear in the longer name.
    Used to surface QB vendors that are probably the same entity as a Ramp vendor
    but spelled differently (e.g. 'COMDATA NETWORK' vs 'COMDATA INC')."""
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return 0
    return int(100 * len(wa & wb) / min(len(wa), len(wb)))


def _nearest_qb_match(vendor_norm: str, amount: float | None,
                       qb: pd.DataFrame) -> dict:
    """For a Ramp bill that didn't match QB, find the closest QB vendor by word
    overlap.  Returns dict with BestQBVendor, BestQBMatchScore, BestQBAmount,
    BestQBInvNum, AmtDiff so the reader can spot false-negative matches."""
    if qb.empty or not vendor_norm:
        return {"BestQBVendor": "", "BestQBMatchScore": 0,
                "BestQBAmount": None, "BestQBInvNum": "", "AmtDiff": None}
    best_score = -1
    best_row: dict = {}
    for _, qr in qb.iterrows():
        score = _word_overlap(vendor_norm, str(qr.get("VendorNorm", "")))
        if score > best_score:
            best_score = score
            best_row = qr.to_dict()
    qb_amt = pd.to_numeric(best_row.get("Open Balance"), errors="coerce") if best_row else None
    amt_diff: float | None = None
    if amount is not None and qb_amt is not None and not pd.isna(qb_amt):
        amt_diff = round(float(amount) - float(qb_amt), 2)
    return {
        "BestQBVendor":    best_row.get("Vendor", "") if best_row else "",
        "BestQBMatchScore": best_score,
        "BestQBAmount":    float(qb_amt) if qb_amt is not None and not pd.isna(qb_amt) else None,
        "BestQBInvNum":    best_row.get("Num", "") if best_row else "",
        "AmtDiff":         amt_diff,
    }


def _flag_ramp_duplicates(not_in_qb: pd.DataFrame) -> pd.Series:
    """Within the AP_Not_In_QB list, flag any bill that looks like a duplicate
    of another: same normalised vendor + amount within 5% + invoice dates within
    30 days.  Returns a Series of string labels (empty string = no dupe detected)."""
    labels = [""] * len(not_in_qb)
    if not_in_qb.empty:
        return pd.Series(labels, index=not_in_qb.index)
    rows = not_in_qb.reset_index(drop=True)
    amounts = pd.to_numeric(rows["AmountTotal"], errors="coerce")
    dates = pd.to_datetime(rows.get("InvoiceDate", pd.Series(dtype="object")),
                           errors="coerce")
    for i in range(len(rows)):
        if labels[i]:          # already flagged as dupe of something
            continue
        vn_i = str(rows.at[i, "VendorNorm"] if "VendorNorm" in rows.columns else "")
        amt_i = amounts.iloc[i]
        dt_i = dates.iloc[i]
        for j in range(i + 1, len(rows)):
            vn_j = str(rows.at[j, "VendorNorm"] if "VendorNorm" in rows.columns else "")
            if vn_i != vn_j or not vn_i:
                continue
            amt_j = amounts.iloc[j]
            if pd.isna(amt_i) or pd.isna(amt_j) or amt_i == 0:
                continue
            if abs(amt_i - amt_j) / max(abs(amt_i), 1) > 0.05:
                continue
            # Same vendor + same amount ± 5% — check date proximity
            dt_j = dates.iloc[j]
            if not pd.isna(dt_i) and not pd.isna(dt_j):
                if abs((dt_i - dt_j).days) > 30:
                    continue
            # Flags both: whichever has the later CreatedAt is the likely dupe
            bill_i = str(rows.at[i, "BillId"] or "")
            bill_j = str(rows.at[j, "BillId"] or "")
            labels[j] = f"POSSIBLE DUPE of {bill_i}"
            if not labels[i]:
                labels[i] = f"POSSIBLE DUPE (see {bill_j})"
    return pd.Series(labels, index=not_in_qb.index)


# ── reconciliation ────────────────────────────────────────────────────────────

def reconcile(qb: pd.DataFrame, ramp: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Returns dict with keys: Summary, AP_Not_In_QB, AP_In_Both, QB_Only.
    """
    if ramp.empty and qb.empty:
        log.warning("Both sources empty — nothing to reconcile")
        return {k: pd.DataFrame() for k in ("Summary", "AP_Not_In_QB", "AP_In_Both", "QB_Only")}

    # Build lookup sets from QB
    qb_vendors: set[str] = set(qb["VendorNorm"].dropna()) if not qb.empty else set()
    qb_inv:     set[str] = set(qb["NumNorm"].dropna()) if not qb.empty else set()

    # ── classify each Ramp bill ───────────────────────────────────────────────
    not_in_qb_rows: list[dict] = []
    in_both_rows:   list[dict] = []

    for _, bill in ramp.iterrows():
        vendor_match = bill["VendorNorm"] in qb_vendors
        inv_match    = bool(bill["NumNorm"]) and bill["NumNorm"] in qb_inv
        matched      = vendor_match or inv_match

        row = {
            "BillId":          bill.get("BillId"),
            "VendorName":      bill.get("VendorName"),
            "VendorNorm":      bill.get("VendorNorm", ""),
            "InvoiceNumber":   bill.get("InvoiceNumber"),
            "InvoiceDate":     bill.get("InvoiceDate"),
            "AmountTotal":     bill.get("AmountTotal"),
            "PaymentStatus":   bill.get("PaymentStatus"),
            "ApprovalStatus":  bill.get("ApprovalStatus"),
            "CreatedAt":       bill.get("CreatedAt"),
            "AgeDays":         bill.get("AgeDays", 0),
            "MatchedOnVendor": vendor_match,
            "MatchedOnInvNum": inv_match,
        }

        if matched:
            in_both_rows.append(row)
        else:
            not_in_qb_rows.append(row)

    not_in_qb = pd.DataFrame(not_in_qb_rows)
    in_both    = pd.DataFrame(in_both_rows)

    # Flag only bills old enough to warrant action
    if not not_in_qb.empty:
        not_in_qb["ActionNeeded"] = not_in_qb["AgeDays"] >= AP_LAG_DAYS
        not_in_qb.sort_values("AgeDays", ascending=False, inplace=True)

        # ── verification columns ──────────────────────────────────────────────
        # Nearest QB match — lets the reader spot false-negative matches where
        # the same vendor is spelled differently in Ramp vs QB.
        match_cols = not_in_qb.apply(
            lambda r: pd.Series(_nearest_qb_match(
                r.get("VendorNorm", ""),
                pd.to_numeric(r.get("AmountTotal"), errors="coerce"),
                qb,
            )),
            axis=1,
        )
        not_in_qb = pd.concat([not_in_qb, match_cols], axis=1)

        # Intra-Ramp duplicate detection
        not_in_qb["RampDupeFlag"] = _flag_ramp_duplicates(not_in_qb)

        # Summary review flag — one column to scan
        def _review_flag(row) -> str:
            flags = []
            if row.get("RampDupeFlag"):
                flags.append(row["RampDupeFlag"])
            score = row.get("BestQBMatchScore", 0) or 0
            if score >= 60:
                flags.append(
                    f"REVIEW: QB has '{row.get('BestQBVendor', '')}' "
                    f"(similarity {score}%, QB open ${row.get('BestQBAmount') or 0:,.0f})"
                )
            return " | ".join(flags)

        not_in_qb["ReviewFlag"] = not_in_qb.apply(_review_flag, axis=1)

    # ── QB bills with no Ramp counterpart (manually entered) ─────────────────
    qb_only_rows: list[dict] = []
    if not qb.empty:
        for _, qb_row in qb.iterrows():
            ramp_vendor_match = qb_row["VendorNorm"] in (ramp["VendorNorm"].values if not ramp.empty else [])
            ramp_inv_match    = (bool(qb_row["NumNorm"]) and
                                 qb_row["NumNorm"] in (ramp["NumNorm"].values if not ramp.empty else []))
            if not ramp_vendor_match and not ramp_inv_match:
                qb_only_rows.append({
                    "Company":        qb_row.get("Company"),
                    "Vendor":         qb_row.get("Vendor"),
                    "InvoiceNum":     qb_row.get("Num"),
                    "BillDate":       qb_row.get("Date"),
                    "DueDate":        qb_row.get("Due Date"),
                    "OpenBalance":    qb_row.get("Open Balance"),
                    "AgingBucket":    qb_row.get("Section"),
                })

    qb_only = pd.DataFrame(qb_only_rows)
    if not qb_only.empty:
        bucket_sort = qb_only["AgingBucket"].map(_BUCKET_ORDER).fillna(99)
        qb_only = qb_only.iloc[bucket_sort.argsort()[::-1]]   # oldest first

    # ── summary ───────────────────────────────────────────────────────────────
    action_count = int(not_in_qb["ActionNeeded"].sum()) if not not_in_qb.empty and "ActionNeeded" in not_in_qb else 0
    action_amount = float(
        pd.to_numeric(
            not_in_qb.loc[not_in_qb.get("ActionNeeded", pd.Series(False, index=not_in_qb.index)), "AmountTotal"],
            errors="coerce"
        ).sum()
    ) if not not_in_qb.empty else 0.0

    qb_open_total = float(pd.to_numeric(qb["Open Balance"], errors="coerce").sum()) if not qb.empty else 0.0
    ramp_unpaid_total = float(pd.to_numeric(ramp["AmountTotal"], errors="coerce").sum()) if not ramp.empty else 0.0

    summary = pd.DataFrame([
        {
            "Check":        "Ramp bills NOT in QB",
            "Total_Bills":  len(not_in_qb),
            "Action_Needed": action_count,
            "Dollar_Amount": f"${action_amount:,.2f}",
            "Threshold":    f">{AP_LAG_DAYS} days old",
            "Note":         "Bills in Ramp not yet entered as QB AP — action for Audra",
        },
        {
            "Check":        "Ramp bills matched in QB",
            "Total_Bills":  len(in_both),
            "Action_Needed": 0,
            "Dollar_Amount": "",
            "Threshold":    "",
            "Note":         "Confirmation: these Ramp bills have a QB counterpart",
        },
        {
            "Check":        "QB bills without Ramp counterpart",
            "Total_Bills":  len(qb_only),
            "Action_Needed": 0,
            "Dollar_Amount": "",
            "Threshold":    "",
            "Note":         "Manually entered AP (no Ramp bill) — expected for some vendors",
        },
        {
            "Check":        "QB total open AP",
            "Total_Bills":  len(qb) if not qb.empty else 0,
            "Action_Needed": 0,
            "Dollar_Amount": f"${qb_open_total:,.2f}",
            "Threshold":    "",
            "Note":         "All companies combined",
        },
        {
            "Check":        "Ramp total unpaid bills",
            "Total_Bills":  len(ramp) if not ramp.empty else 0,
            "Action_Needed": 0,
            "Dollar_Amount": f"${ramp_unpaid_total:,.2f}",
            "Threshold":    "",
            "Note":         "Excludes PAID / CANCELED",
        },
    ])

    return {
        "Summary":      summary,
        "AP_Not_In_QB": not_in_qb,
        "AP_In_Both":   in_both,
        "QB_Only":      qb_only,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    az_tenant = os.environ.get("AZURE_TENANT_ID", "")
    az_client = os.environ.get("AZURE_CLIENT_ID", "")
    az_secret = os.environ.get("AZURE_CLIENT_SECRET", "")
    upn       = os.environ.get("ONEDRIVE_USER_UPN", "")

    missing = [k for k, v in {
        "AZURE_TENANT_ID": az_tenant,
        "AZURE_CLIENT_ID": az_client,
        "AZURE_CLIENT_SECRET": az_secret,
        "ONEDRIVE_USER_UPN": upn,
    }.items() if not v]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    graph_token = get_token(az_tenant, az_client, az_secret)

    log.info("Loading QB AP…")
    qb = _load_qb_ap(graph_token, upn)

    log.info("Loading Ramp bills…")
    ramp = _load_ramp_bills(graph_token, upn)

    log.info("Reconciling…")
    sheets = reconcile(qb, ramp)

    # Print summary to log
    summ = sheets["Summary"]
    for _, row in summ.iterrows():
        flag = " ⚠" if row["Action_Needed"] > 0 else ""
        log.info("  %-40s  bills=%-4d  action=%-4d  %s%s",
                 row["Check"], row["Total_Bills"], row["Action_Needed"],
                 row["Dollar_Amount"], flag)

    # Write Excel
    out_path = Path("output/reconciliation/Recon_Master.xlsx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        sheets["Summary"].to_excel(writer,      sheet_name="Summary",      index=False)
        sheets["AP_Not_In_QB"].to_excel(writer, sheet_name="AP_Not_In_QB", index=False)
        sheets["AP_In_Both"].to_excel(writer,   sheet_name="AP_In_Both",   index=False)
        sheets["QB_Only"].to_excel(writer,      sheet_name="QB_Only",      index=False)
    log.info("Wrote %s", out_path)

    # Upload
    ensure_folder(graph_token, upn, "Reconciliation")
    upload_file(graph_token, upn, "Reconciliation", "Recon_Master.xlsx", out_path)
    log.info("Uploaded to OneDrive/Reconciliation/ ✓")

    # Exit non-zero if action items exist (makes the GitHub Actions step visibly amber)
    action_total = int(sheets["Summary"]["Action_Needed"].sum())
    if action_total > 0:
        log.warning("%d Ramp bills need QB entry — see AP_Not_In_QB sheet", action_total)


if __name__ == "__main__":
    main()
