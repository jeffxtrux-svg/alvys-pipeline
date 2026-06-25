# XFreight Accounting Pipeline — Build Specification

**Repo:** `jeffxtrux-svg/alvys-pipeline` (`~/Code/alvys-pipeline`)
**Status as of 2026-06-19:** Identifies gaps; defines new connectors + reconciliation layer
**Tech pattern:** Python → GitHub Actions → OneDrive Excel → Power BI  
_(matches existing Alvys/QB/Samsara connectors — no new infrastructure required)_

---

## Quick Reference

| Connector | Status | Cadence | Output File |
|---|---|---|---|
| Alvys (Loads/Trips/Fuel) | **LIVE** | 3×/day | `Alvys Master2026.xlsx` |
| QuickBooks (5 entities) | **LIVE** | 8×/day | `QuickBooks/QB_*.xlsx` |
| Samsara (fleet telemetry) | **LIVE** | 3×/day | `Samsara/Samsara Master.xlsx` |
| SambaSafety (driver risk) | **LIVE** | 1×/day | `SambaSafety/SambaSafety_Master.xlsx` |
| **Ramp (AP + card spend)** | **BUILD** | 8×/day | `Ramp/Ramp_Master.xlsx` |
| **Comdata (fuel cards)** | **BUILD** | 2×/day | `Comdata/Comdata_Master.xlsx` |
| **Triumph (factoring)** | **BUILD** | 2×/day | `Factoring/Triumph_Master.xlsx` |
| **Reconciliation engine** | **BUILD** | 1×/day | `Reconciliation/Recon_Master.xlsx` |

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                                │
├──────────┬──────────┬──────────┬───────────┬────────┬──────────┤
│  Alvys   │    QB    │ Samsara  │   Ramp    │Comdata │ Triumph  │
│  (SFTP)  │ (OAuth)  │  (REST)  │  (REST)   │ (SFTP) │ (REST/  │
│          │  5 cos.  │          │  OAuth2   │  CSV   │  SFTP)  │
└────┬─────┴────┬─────┴────┬─────┴─────┬─────┴───┬────┴────┬─────┘
     │          │          │           │         │         │
     ▼          ▼          ▼           ▼         ▼         ▼
┌─────────────────────────────────────────────────────────────────┐
│              GITHUB ACTIONS (ubuntu-latest)                     │
│   Python 3.11 │ pandas │ openpyxl │ requests │ paramiko        │
│   Separate workflow per source; refresh_all.yml fans out        │
└────────────────────────────┬────────────────────────────────────┘
                             │  writes .xlsx
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              OneDrive (xfreight.net / Graph API)                │
│                                                                 │
│  /QuickBooks/QB_*.xlsx          /Ramp/Ramp_Master.xlsx          │
│  Alvys Master2026.xlsx          /Comdata/Comdata_Master.xlsx    │
│  /Samsara/Samsara Master.xlsx   /Factoring/Triumph_Master.xlsx  │
│                                 /Reconciliation/Recon_*.xlsx    │
└────────────────────────────┬────────────────────────────────────┘
                             │  Power BI DirectQuery / scheduled
                             ▼
┌──────────────────────┐  ┌──────────────────────────────────────┐
│   Power BI Service   │  │  Email Briefs (daily, Graph Mail)    │
│  XFreight Dashboard  │  │  scorecard_email / financial_email   │
│  (existing reports   │  │  + new accounting_email (BUILD)      │
│   + new recon tabs)  │  └──────────────────────────────────────┘
└──────────────────────┘
                             │  also writes
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│           Karpathy-Wiki (Decision Engine)                       │
│  risk-register.md: auto-flag AR>45d, AP pile-up, LOC near max  │
│  decision-journal.md: factoring decision outcome tracking       │
│  Phase 2 daily metrics row appended after each recon run        │
└─────────────────────────────────────────────────────────────────┘
```

### Entity Money Flow (intercompany — drives reconciliation logic)

```
  Customers ──► X-Trux Inc ──► Truk-Way Leasing  (driver wages + truck debt)
  (AR)                    │──► N&J Trailers       (~$21K/mo trailer lease)
                          │──► N&J Properties     (~$5K/mo building rent)
                          └──► X-Linx Inc         (brokered load revenue, separate)
```

Reconciliation must trace payments ACROSS entities, not just within them.

---

## 2. What's Already Live (Do Not Rebuild)

### QuickBooks connector (`src/qb_client.py` + `qb_reports.py` + `qb_main.py`)
- Pulls 12 report types + 3 entity lists per company, 5 companies
- OAuth 2.0 with automatic refresh token rotation to GitHub Secrets via `gh`
- Output: `QB_ProfitAndLoss.xlsx`, `QB_AgedReceivableDetail.xlsx`, `QB_AgedPayableDetail.xlsx`, etc.
- **Extend, don't replace:** the reconciliation engine reads these QB outputs directly

### Financial email (`src/financial_email.py`)
- Already produces QB-vs-Alvys AR variance, un-invoiced load list, carrier bill gaps
- Reads: `Alvys Pipeline.xlsx`, `QB_AgedReceivableDetail.xlsx`, `QB_Bills.xlsx`
- **Extend:** new `src/accounting_email.py` adds Ramp AP, Comdata fuel, cash position

### OneDrive upload pattern (`src/onedrive_upload.py`)
- `get_token(tenant, client_id, secret)` → `upload_file(token, upn, path, data)`
- All new connectors call this. Do not write a new upload client.

---

## 3. New Connector: Ramp (AP + Card Spend)

**Why:** QB shows AP after bills are entered manually. Ramp is where the actual bills land first — the gap between "Ramp received bill" and "bill entered in QB" is the AP blind spot. Comdata fuel card charges flow through Ramp too (corporate card settlements).

**Auth:** OAuth 2.0 client credentials
```
POST https://api.ramp.com/developer/v1/token
Body: grant_type=client_credentials&scope=bills:read transactions:read users:read vendors:read
```

### `src/ramp_client.py`

```python
"""Ramp REST API client — bills, card transactions, vendors, users.

GitHub Secrets:
    RAMP_CLIENT_ID      — from Ramp Developer Settings → Applications
    RAMP_CLIENT_SECRET  — same app
"""
from __future__ import annotations
import logging
import time
from typing import Any, Iterator
import requests

log = logging.getLogger("ramp_client")

TOKEN_URL = "https://api.ramp.com/developer/v1/token"
BASE_URL  = "https://api.ramp.com/developer/v1"


class RampClient:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    # ── auth ──────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "scope": "bills:read transactions:read users:read vendors:read",
            },
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600) - 60

    def _token(self) -> str:
        if not self._access_token or time.time() >= self._expires_at:
            self._refresh()
        return self._access_token  # type: ignore[return-value]

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = requests.get(
            f"{BASE_URL}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self._token()}"},
            params=params or {},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, params: dict | None = None) -> Iterator[dict]:
        """Yield every item across all pages (cursor-based)."""
        p = dict(params or {})
        p.setdefault("page_size", 100)
        while True:
            data = self._get(path, p)
            yield from data.get("data", [])
            next_cursor = data.get("page", {}).get("next")
            if not next_cursor:
                break
            p["start"] = next_cursor

    # ── public endpoints ──────────────────────────────────────────────────────

    def bills(self, from_date: str | None = None) -> list[dict]:
        """All bills (AP). from_date: YYYY-MM-DD."""
        params: dict = {}
        if from_date:
            params["from_date"] = from_date
        return list(self._paginate("/bills", params))

    def transactions(self, from_date: str | None = None) -> list[dict]:
        """All card transactions. from_date: YYYY-MM-DD."""
        params: dict = {}
        if from_date:
            params["from_date"] = from_date
        return list(self._paginate("/transactions", params))

    def vendors(self) -> list[dict]:
        return list(self._paginate("/vendors"))

    def users(self) -> list[dict]:
        return list(self._paginate("/users"))

    def departments(self) -> list[dict]:
        return list(self._paginate("/departments"))
```

### `src/ramp_main.py`

```python
"""Ramp data pull — writes Ramp_Master.xlsx to OneDrive/Ramp/."""
from __future__ import annotations
import logging, os, datetime
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from .ramp_client import RampClient
from .onedrive_upload import get_token, upload_file, ensure_folder

log = logging.getLogger("ramp_main")

# ── field normalisation ───────────────────────────────────────────────────────

def _bills_df(rows: list[dict]) -> pd.DataFrame:
    records = []
    for b in rows:
        records.append({
            "BillId":         b.get("id"),
            "VendorName":     (b.get("vendor") or {}).get("name"),
            "InvoiceNumber":  b.get("invoice_number"),
            "InvoiceDate":    b.get("invoice_date"),
            "DueDate":        b.get("due_date"),
            "AmountTotal":    b.get("amount", {}).get("amount"),
            "AmountCurrency": b.get("amount", {}).get("currency_code"),
            "PaymentStatus":  b.get("payment_status"),
            "ApprovalStatus": b.get("approval_status"),
            "CreatedAt":      b.get("created_at"),
            "PaidAt":         b.get("paid_at"),
            "Memo":           b.get("memo"),
        })
    return pd.DataFrame(records)


def _transactions_df(rows: list[dict]) -> pd.DataFrame:
    records = []
    for t in rows:
        records.append({
            "TransactionId":   t.get("id"),
            "CardholderName":  (t.get("card_holder") or {}).get("name"),
            "MerchantName":    (t.get("merchant") or {}).get("name"),
            "MerchantId":      (t.get("merchant") or {}).get("id"),
            "Amount":          t.get("amount"),
            "CurrencyCode":    t.get("currency_code"),
            "UserTransAmount": t.get("user_transaction_time"),
            "TransactionDate": t.get("user_transaction_time", "")[:10],
            "State":           t.get("state"),
            "PolicyViolation": t.get("policy_violations", [None])[0],
            "ReceiptMissing":  len(t.get("receipts", [])) == 0,
            "MemoText":        t.get("memo"),
            "AccountingCode":  (t.get("accounting_field_selections") or [{}])[0].get("value"),
        })
    return pd.DataFrame(records)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    load_dotenv()

    client_id     = os.environ["RAMP_CLIENT_ID"]
    client_secret = os.environ["RAMP_CLIENT_SECRET"]
    az_tenant     = os.environ["AZURE_TENANT_ID"]
    az_client     = os.environ["AZURE_CLIENT_ID"]
    az_secret     = os.environ["AZURE_CLIENT_SECRET"]
    upn           = os.environ["ONEDRIVE_USER_UPN"]

    ramp = RampClient(client_id, client_secret)

    # Pull YTD by default; for hourly runs pull last 7d to stay fast
    from_date = str(datetime.date.today().replace(month=1, day=1))

    log.info("Pulling Ramp bills…")
    bills_df = _bills_df(ramp.bills(from_date))
    log.info("  %d bills", len(bills_df))

    log.info("Pulling Ramp card transactions…")
    txn_df = _transactions_df(ramp.transactions(from_date))
    log.info("  %d transactions", len(txn_df))

    vendors_df  = pd.DataFrame(ramp.vendors())
    users_df    = pd.DataFrame(ramp.users())

    out_path = Path("output/ramp/Ramp_Master.xlsx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        bills_df.to_excel(writer, sheet_name="Bills", index=False)
        txn_df.to_excel(writer, sheet_name="Transactions", index=False)
        vendors_df.to_excel(writer, sheet_name="Vendors", index=False)
        users_df.to_excel(writer, sheet_name="Users", index=False)
    log.info("Wrote %s", out_path)

    graph_token = get_token(az_tenant, az_client, az_secret)
    ensure_folder(graph_token, upn, "Ramp")
    upload_file(graph_token, upn, "Ramp/Ramp_Master.xlsx", out_path.read_bytes())
    log.info("Uploaded to OneDrive/Ramp/ ✓")


if __name__ == "__main__":
    main()
```

### Workflow: `.github/workflows/ramp_refresh.yml`

```yaml
# Ramp AP + card transaction refresh — 8× daily (every 2h, 4am–6pm CT)
# Matches QB cadence; AP bills need to be visible same-day for Audra's brief.
#
# GitHub Secrets required:
#   RAMP_CLIENT_ID, RAMP_CLIENT_SECRET
#   AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
#   ONEDRIVE_USER_UPN

name: Refresh Ramp data

on:
  workflow_dispatch:
  workflow_call:
  schedule:
    - cron: '15 0,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23 * * *'

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'

jobs:
  refresh:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Gate to allowed CT hours
        id: ct_gate
        if: github.event_name == 'schedule'
        run: |
          CT_HOUR=$(TZ=America/Chicago date +%-H)
          case "$CT_HOUR" in
            4|6|8|10|12|14|16|18) echo "Target slot." ;;
            *) echo "skip=1" >> "$GITHUB_OUTPUT" ;;
          esac

      - uses: actions/checkout@v4
        if: steps.ct_gate.outputs.skip != '1'

      - uses: actions/setup-python@v5
        if: steps.ct_gate.outputs.skip != '1'
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        if: steps.ct_gate.outputs.skip != '1'
        run: pip install -r requirements.txt

      - name: Pull Ramp data
        if: steps.ct_gate.outputs.skip != '1'
        env:
          RAMP_CLIENT_ID:     ${{ secrets.RAMP_CLIENT_ID }}
          RAMP_CLIENT_SECRET: ${{ secrets.RAMP_CLIENT_SECRET }}
          AZURE_TENANT_ID:    ${{ secrets.AZURE_TENANT_ID }}
          AZURE_CLIENT_ID:    ${{ secrets.AZURE_CLIENT_ID }}
          AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
          ONEDRIVE_USER_UPN:  ${{ secrets.ONEDRIVE_USER_UPN }}
        run: python -m src.ramp_main
```

---

## 4. New Connector: Comdata Fuel Cards

**Why:** Comdata is the fuel card processor for the Truk-Way fleet. Card charges appear on Comdata's SFTP before they land in QB. Cross-referencing Comdata with Samsara fuel telemetry catches misuse and validates GL entries.

**Auth:** SFTP with SSH key (Comdata provides credentials in their portal)
**Delivery:** Comdata posts daily CSV transaction reports to an SFTP server
**Report types:** `TransactionDetail`, `CardActivity`, `TaxSummary`

### `src/comdata_client.py`

```python
"""Comdata fuel card SFTP connector.

Comdata SFTP details (configure via GitHub Secrets):
    COMDATA_SFTP_HOST  — sftp.comdata.com (or account-specific host)
    COMDATA_SFTP_USER  — provided by Comdata
    COMDATA_SFTP_KEY   — base64-encoded SSH private key
    COMDATA_SFTP_PATH  — remote directory (e.g. /reports/)

Comdata posts CSVs with naming like:
    TRANS_DETAIL_YYYYMMDD.csv
    CARD_ACTIVITY_YYYYMMDD.csv
"""
from __future__ import annotations
import base64
import io
import logging
import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path
import paramiko
import pandas as pd

log = logging.getLogger("comdata_client")

# Column name normalisation map (Comdata headers vary by report type)
_TRANS_COLS = {
    "CARD NUMBER":          "CardNumber",
    "DRIVER ID":            "DriverId",
    "UNIT NUMBER":          "UnitNumber",
    "TRANSACTION DATE":     "TransactionDate",
    "TRANSACTION TIME":     "TransactionTime",
    "SITE NAME":            "SiteName",
    "CITY":                 "City",
    "STATE":                "State",
    "PRODUCT CODE":         "ProductCode",
    "PRODUCT DESCRIPTION":  "ProductDescription",
    "QUANTITY":             "Quantity",
    "UNIT PRICE":           "UnitPrice",
    "AMOUNT":               "Amount",
    "ODOMETER":             "Odometer",
    "INVOICE NUMBER":       "InvoiceNumber",
    "POSTING DATE":         "PostingDate",
}


class ComdataClient:
    def __init__(
        self,
        host: str,
        username: str,
        private_key_b64: str,
        remote_path: str = "/reports/",
    ) -> None:
        self.host = host
        self.username = username
        self._key_b64 = private_key_b64
        self.remote_path = remote_path

    def _connect(self) -> paramiko.SFTPClient:
        key_bytes = base64.b64decode(self._key_b64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as f:
            f.write(key_bytes)
            key_path = f.name
        pkey = paramiko.RSAKey.from_private_key_file(key_path)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(self.host, username=self.username, pkey=pkey)
        return ssh.open_sftp()

    def latest_reports(self, days_back: int = 7) -> dict[str, pd.DataFrame]:
        """Download and parse the most recent N days of transaction files."""
        sftp = self._connect()
        try:
            all_files = sftp.listdir(self.remote_path)
        except FileNotFoundError:
            log.warning("Comdata remote path %s not found", self.remote_path)
            return {}

        cutoff = date.today() - timedelta(days=days_back)
        results: dict[str, pd.DataFrame] = {}

        for fname in sorted(all_files):
            m = re.search(r"(\d{8})", fname)
            if not m:
                continue
            file_date = date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:]))
            if file_date < cutoff:
                continue

            raw = io.BytesIO()
            sftp.getfo(f"{self.remote_path}/{fname}", raw)
            raw.seek(0)

            try:
                df = pd.read_csv(raw, dtype=str)
                df.rename(columns=_TRANS_COLS, inplace=True, errors="ignore")
                df["SourceFile"] = fname
                df["FileDate"]   = str(file_date)

                # Numeric coercion
                for col in ("Amount", "Quantity", "UnitPrice", "Odometer"):
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                results[fname] = df
                log.info("  Parsed %s (%d rows)", fname, len(df))
            except Exception as exc:
                log.warning("  Failed to parse %s: %s", fname, exc)

        sftp.close()
        return results
```

### `src/comdata_main.py`

```python
"""Comdata data pull — writes Comdata_Master.xlsx to OneDrive/Comdata/."""
from __future__ import annotations
import logging, os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from .comdata_client import ComdataClient
from .onedrive_upload import get_token, upload_file, ensure_folder

log = logging.getLogger("comdata_main")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    load_dotenv()

    client = ComdataClient(
        host=os.environ["COMDATA_SFTP_HOST"],
        username=os.environ["COMDATA_SFTP_USER"],
        private_key_b64=os.environ["COMDATA_SFTP_KEY"],
        remote_path=os.environ.get("COMDATA_SFTP_PATH", "/reports/"),
    )

    report_dfs = client.latest_reports(days_back=90)  # YTD or 90d, whichever
    if not report_dfs:
        log.warning("No Comdata files found — no output written")
        return

    combined = pd.concat(list(report_dfs.values()), ignore_index=True)
    combined.drop_duplicates(subset=["InvoiceNumber"], inplace=True)

    out_path = Path("output/comdata/Comdata_Master.xlsx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="Transactions", index=False)

    graph_token = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )
    ensure_folder(graph_token, os.environ["ONEDRIVE_USER_UPN"], "Comdata")
    upload_file(graph_token, os.environ["ONEDRIVE_USER_UPN"],
                "Comdata/Comdata_Master.xlsx", out_path.read_bytes())
    log.info("Uploaded Comdata_Master.xlsx ✓  (%d rows)", len(combined))


if __name__ == "__main__":
    main()
```

**Fuel Cross-Reference (Power BI side):**  
In Power BI, join `Comdata_Master[UnitNumber]` → `Samsara Master[Vehicle Name]` (after `_clean_vehicle_name` normalisation). Comdata `Amount` vs Samsara `VehicleStats[fuelPercent]` change → variance flags units with card swipes but no telemetry movement (idle-engine fueling vs driver-charged to wrong unit).

---

## 5. New Connector: Triumph Factoring

**Why:** If X-Trux factors receivables via Triumph, the cash advances come before QB records the payment. Without a Triumph feed the LOC picture is incomplete: QB shows the open AR, Triumph shows the advance (cash in), and the spread = the factoring fee + reserve.

**Status:** Evaluate whether to build — depends on factoring go/no-go decision. If using RTS instead, the same pattern applies; swap the base URL.

**Auth options:**
- Triumph Partner Portal REST API (OAuth 2.0, available to enrolled carriers)
- SFTP settlement reports (Triumph delivers daily CSVs to an SFTP you configure)

### `src/triumph_client.py`

```python
"""Triumph Business Capital factoring connector.

Two modes:
  - REST API (preferred): full real-time invoice status
  - SFTP (fallback): daily settlement CSV if Triumph hasn't enabled API access

GitHub Secrets:
    TRIUMPH_API_KEY     — from Triumph carrier portal
    TRIUMPH_COMPANY_ID  — your Triumph account/carrier ID
    # OR for SFTP mode:
    TRIUMPH_SFTP_HOST / TRIUMPH_SFTP_USER / TRIUMPH_SFTP_KEY / TRIUMPH_SFTP_PATH
"""
from __future__ import annotations
import logging, os
from typing import Any
import requests
import pandas as pd

log = logging.getLogger("triumph_client")

BASE_URL = "https://api.triumphbusinesscapital.com/v1"   # confirm with Triumph


class TriumphClient:
    def __init__(self, api_key: str, company_id: str) -> None:
        self.api_key = api_key
        self.company_id = company_id
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        })

    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = self._session.get(f"{BASE_URL}/{path}", params=params or {}, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def invoices(self, status: str | None = None) -> pd.DataFrame:
        """
        Returns DataFrame with columns:
            InvoiceId, InvoiceNumber, CustomerName, InvoiceDate,
            InvoiceAmount, AdvanceAmount, FeeAmount, ReserveAmount,
            PaidDate, Status, FundedDate
        """
        params = {"company_id": self.company_id}
        if status:
            params["status"] = status   # FUNDED, COLLECTED, PENDING, etc.
        raw = self._get("invoices", params)
        rows = raw.get("invoices", raw) if isinstance(raw, dict) else raw
        records = []
        for inv in rows:
            records.append({
                "InvoiceId":      inv.get("id"),
                "InvoiceNumber":  inv.get("invoice_number"),
                "CustomerName":   inv.get("debtor_name") or inv.get("customer_name"),
                "InvoiceDate":    inv.get("invoice_date"),
                "DueDate":        inv.get("due_date"),
                "InvoiceAmount":  inv.get("invoice_amount"),
                "AdvanceAmount":  inv.get("advance_amount"),
                "FeeAmount":      inv.get("fee_amount"),
                "FeeRate":        inv.get("fee_rate"),
                "ReserveAmount":  inv.get("reserve_amount"),
                "FundedDate":     inv.get("funded_date"),
                "PaidDate":       inv.get("paid_date"),
                "Status":         inv.get("status"),
            })
        return pd.DataFrame(records)

    def reserve_balance(self) -> dict:
        """Current reserve held by Triumph (cash withheld pending collections)."""
        return self._get(f"companies/{self.company_id}/reserve")

    def advances_ytd(self) -> pd.DataFrame:
        """All advances paid out this year — the cash-in side."""
        raw = self._get("advances", {"company_id": self.company_id})
        rows = raw.get("advances", raw) if isinstance(raw, dict) else raw
        return pd.DataFrame(rows)
```

### Workflow: `.github/workflows/triumph_refresh.yml`

```yaml
# Triumph factoring refresh — 2× daily (7am + 3pm CT)
# No need to match QB cadence; Triumph settles once per day.
name: Refresh Triumph factoring data
on:
  workflow_dispatch:
  schedule:
    - cron: '0 12 * * *'   # 7am CDT / 6am CST (gate confirms)
    - cron: '0 20 * * *'   # 3pm CDT / 2pm CST
jobs:
  refresh:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11', cache: pip }
      - run: pip install -r requirements.txt
      - name: Pull Triumph data
        env:
          TRIUMPH_API_KEY:     ${{ secrets.TRIUMPH_API_KEY }}
          TRIUMPH_COMPANY_ID:  ${{ secrets.TRIUMPH_COMPANY_ID }}
          AZURE_TENANT_ID:     ${{ secrets.AZURE_TENANT_ID }}
          AZURE_CLIENT_ID:     ${{ secrets.AZURE_CLIENT_ID }}
          AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
          ONEDRIVE_USER_UPN:   ${{ secrets.ONEDRIVE_USER_UPN }}
        run: python -m src.triumph_main
```

---

## 6. Reconciliation Engine

**Why:** Each source sees a slice of the same cash. The reconciliation engine joins them to find mismatches before they become month-end surprises.

**Four reconciliations, one output file:**

| Check | Source A | Source B | Flag When |
|---|---|---|---|
| **AR match** | QB Aged Receivables (by customer) | Alvys delivered & invoiced loads | QB AR ≠ Alvys invoiced ± $50 |
| **AP match** | QB Aged Payables (by vendor) | Ramp bills (by vendor) | Bill in Ramp but not in QB > 3 days |
| **Fuel GL match** | QB fuel expense (GL 6xxx) | Comdata card charges (by posting date) | Variance > $200/month |
| **Intercompany check** | QB X-Trux payables to related parties | QB Truk-Way / N&J / N&J receivables | Mismatch > $500 |

### `src/accounting_reconciliation.py`

```python
"""Cross-source accounting reconciliation.

Reads from OneDrive (all sources must have already run):
    QB_AgedReceivableDetail.xlsx   → AR by customer
    QB_AgedPayableDetail.xlsx      → AP by vendor
    QB_GeneralLedger.xlsx          → fuel GL entries
    Ramp_Master.xlsx               → Bills sheet
    Comdata_Master.xlsx            → Transactions sheet
    Alvys Pipeline.xlsx            → Trips sheet (delivered loads, invoice #s)

Writes: Recon_Master.xlsx → OneDrive/Reconciliation/
Sheets: AR_Match, AP_Match, Fuel_Match, Intercompany_Check, Summary
"""
from __future__ import annotations
import datetime, logging, os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from .onedrive_upload import download_file, ensure_folder, get_token, upload_file

log = logging.getLogger("accounting_recon")

# Threshold constants — override via env
AR_TOLERANCE_USD    = float(os.environ.get("RECON_AR_TOLERANCE",    "50"))
AP_RAMP_LAG_DAYS    = int(os.environ.get("RECON_AP_LAG_DAYS",       "3"))
FUEL_TOLERANCE_USD  = float(os.environ.get("RECON_FUEL_TOLERANCE",  "200"))
IC_TOLERANCE_USD    = float(os.environ.get("RECON_IC_TOLERANCE",    "500"))


# ── loaders ──────────────────────────────────────────────────────────────────

def _load(graph_token: str, upn: str, od_path: str) -> pd.DataFrame:
    """Download one xlsx from OneDrive; return first sheet as DataFrame."""
    try:
        raw = download_file(graph_token, upn, od_path)
        return pd.read_excel(raw, dtype=str)
    except Exception as exc:
        log.warning("Could not load %s: %s — returning empty", od_path, exc)
        return pd.DataFrame()


def _load_sheet(graph_token: str, upn: str, od_path: str, sheet: str) -> pd.DataFrame:
    try:
        raw = download_file(graph_token, upn, od_path)
        return pd.read_excel(raw, sheet_name=sheet, dtype=str)
    except Exception as exc:
        log.warning("Could not load %s[%s]: %s", od_path, sheet, exc)
        return pd.DataFrame()


# ── reconciliations ───────────────────────────────────────────────────────────

def reconcile_ar(qb_ar: pd.DataFrame, alvys_trips: pd.DataFrame) -> pd.DataFrame:
    """
    QB AR by customer  vs  Alvys invoiced loads by customer.

    QB AR:    columns include 'Customer', 'Current', '1-30', '31-60', '61-90', '91+'
    Alvys:    trips sheet; filter to status not 'Open'; sum 'Customer Rate' by customer

    Returns mismatch rows with flag column.
    """
    if qb_ar.empty or alvys_trips.empty:
        return pd.DataFrame()

    # Normalise customer names (upper, strip punctuation) for fuzzy-ish join
    def _norm(s):
        return str(s).upper().strip().replace(",", "").replace(".", "").replace("  ", " ")

    # QB side: total open AR per customer
    amount_cols = [c for c in qb_ar.columns if c not in ("Customer", "Company")]
    qb_ar = qb_ar.copy()
    for col in amount_cols:
        qb_ar[col] = pd.to_numeric(qb_ar[col], errors="coerce").fillna(0)
    qb_ar["QB_AR_Total"] = qb_ar[amount_cols].sum(axis=1)
    qb_ar["CustomerNorm"] = qb_ar["Customer"].apply(_norm)
    qb_totals = qb_ar.groupby("CustomerNorm")["QB_AR_Total"].sum().reset_index()

    # Alvys side: delivered + invoiced loads, not Open
    trips = alvys_trips.copy()
    open_statuses = {"open", "cancelled"}
    if "Status" in trips.columns:
        trips = trips[~trips["Status"].str.lower().isin(open_statuses)]
    if "Customer Rate" in trips.columns:
        trips["CustomerRate"] = pd.to_numeric(trips["Customer Rate"], errors="coerce").fillna(0)
    if "Customer Name" in trips.columns:
        trips["CustomerNorm"] = trips["Customer Name"].apply(_norm)
    alvys_totals = trips.groupby("CustomerNorm")["CustomerRate"].sum().reset_index()
    alvys_totals.rename(columns={"CustomerRate": "Alvys_AR_Total"}, inplace=True)

    merged = qb_totals.merge(alvys_totals, on="CustomerNorm", how="outer").fillna(0)
    merged["Variance"] = merged["QB_AR_Total"] - merged["Alvys_AR_Total"]
    merged["Flag"] = merged["Variance"].abs() > AR_TOLERANCE_USD

    return merged.sort_values("Variance", ascending=False)


def reconcile_ap(qb_ap: pd.DataFrame, ramp_bills: pd.DataFrame) -> pd.DataFrame:
    """
    QB AP (by vendor)  vs  Ramp bills (by vendor).

    Bills in Ramp but absent from QB for > AP_RAMP_LAG_DAYS are flagged
    as 'Not entered in QB' — these are Audra's action items.
    """
    if ramp_bills.empty:
        return pd.DataFrame()

    today = datetime.date.today()

    if "InvoiceDate" in ramp_bills.columns:
        ramp_bills = ramp_bills.copy()
        ramp_bills["InvoiceDate"] = pd.to_datetime(ramp_bills["InvoiceDate"], errors="coerce")
        ramp_bills["AgeDays"] = (pd.Timestamp(today) - ramp_bills["InvoiceDate"]).dt.days

    # QB vendor totals
    qb_vendors: dict[str, float] = {}
    if not qb_ap.empty and "Vendor" in qb_ap.columns:
        def _norm(s): return str(s).upper().strip()
        amount_cols = [c for c in qb_ap.columns if c not in ("Vendor", "Company")]
        for col in amount_cols:
            qb_ap[col] = pd.to_numeric(qb_ap[col], errors="coerce").fillna(0)
        qb_ap["Total"] = qb_ap[amount_cols].sum(axis=1)
        for _, row in qb_ap.iterrows():
            vnd = _norm(row["Vendor"])
            qb_vendors[vnd] = qb_vendors.get(vnd, 0) + row["Total"]

    def _vnd_norm(s): return str(s).upper().strip() if s else "UNKNOWN"
    ramp_bills = ramp_bills.copy()
    if "VendorName" in ramp_bills.columns:
        ramp_bills["VendorNorm"] = ramp_bills["VendorName"].apply(_vnd_norm)

    ramp_bills["QB_Balance"] = ramp_bills["VendorNorm"].map(
        lambda v: qb_vendors.get(v, 0)
    )
    lag_threshold = AP_RAMP_LAG_DAYS
    ramp_bills["Flag_NotInQB"] = (
        (ramp_bills.get("AgeDays", pd.Series(dtype=float)) > lag_threshold) &
        (ramp_bills["QB_Balance"] == 0)
    )

    return ramp_bills[[
        "BillId", "VendorName", "InvoiceNumber", "InvoiceDate",
        "AmountTotal", "PaymentStatus", "ApprovalStatus",
        "AgeDays", "QB_Balance", "Flag_NotInQB",
    ]].copy()


def reconcile_fuel(qb_gl: pd.DataFrame, comdata: pd.DataFrame) -> pd.DataFrame:
    """
    QB fuel GL entries (account 6xxx or named 'Fuel')  vs  Comdata card charges.
    Monthly bucketing.
    """
    if qb_gl.empty or comdata.empty:
        return pd.DataFrame()

    # QB: filter to fuel accounts
    gl = qb_gl.copy()
    if "Account" in gl.columns and "Amount" in gl.columns:
        gl["Amount"] = pd.to_numeric(gl["Amount"], errors="coerce").fillna(0)
        fuel_gl = gl[
            gl["Account"].str.contains("fuel|diesel|gas", case=False, na=False) |
            gl["Account"].str.match(r"^6\d{3}", na=False)
        ].copy()
        if "Date" in fuel_gl.columns:
            fuel_gl["Month"] = pd.to_datetime(fuel_gl["Date"], errors="coerce").dt.to_period("M").astype(str)
        qb_by_month = fuel_gl.groupby("Month")["Amount"].sum().reset_index()
        qb_by_month.rename(columns={"Amount": "QB_Fuel"}, inplace=True)
    else:
        qb_by_month = pd.DataFrame(columns=["Month", "QB_Fuel"])

    # Comdata: sum by month
    cd = comdata.copy()
    if "PostingDate" in cd.columns and "Amount" in cd.columns:
        cd["Month"] = pd.to_datetime(cd["PostingDate"], errors="coerce").dt.to_period("M").astype(str)
        cd_by_month = cd.groupby("Month")["Amount"].sum().reset_index()
        cd_by_month.rename(columns={"Amount": "Comdata_Fuel"}, inplace=True)
    else:
        cd_by_month = pd.DataFrame(columns=["Month", "Comdata_Fuel"])

    merged = qb_by_month.merge(cd_by_month, on="Month", how="outer").fillna(0)
    merged["Variance"] = merged["QB_Fuel"] - merged["Comdata_Fuel"]
    merged["Flag"] = merged["Variance"].abs() > FUEL_TOLERANCE_USD
    return merged


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    load_dotenv()

    az_tenant  = os.environ["AZURE_TENANT_ID"]
    az_client  = os.environ["AZURE_CLIENT_ID"]
    az_secret  = os.environ["AZURE_CLIENT_SECRET"]
    upn        = os.environ["ONEDRIVE_USER_UPN"]

    graph_token = get_token(az_tenant, az_client, az_secret)

    log.info("Loading source data…")
    qb_ar    = _load(graph_token, upn, "QuickBooks/QB_AgedReceivableDetail.xlsx")
    qb_ap    = _load(graph_token, upn, "QuickBooks/QB_AgedPayableDetail.xlsx")
    qb_gl    = _load(graph_token, upn, "QuickBooks/QB_GeneralLedger.xlsx")
    ramp     = _load_sheet(graph_token, upn, "Ramp/Ramp_Master.xlsx", "Bills")
    comdata  = _load_sheet(graph_token, upn, "Comdata/Comdata_Master.xlsx", "Transactions")
    alvys    = _load_sheet(graph_token, upn, "Alvys Pipeline.xlsx", "Trips")

    log.info("Running reconciliations…")
    ar_df    = reconcile_ar(qb_ar, alvys)
    ap_df    = reconcile_ap(qb_ap, ramp)
    fuel_df  = reconcile_fuel(qb_gl, comdata)

    # Summary row counts
    ar_flags    = int(ar_df["Flag"].sum()) if not ar_df.empty and "Flag" in ar_df else 0
    ap_flags    = int(ap_df["Flag_NotInQB"].sum()) if not ap_df.empty else 0
    fuel_flags  = int(fuel_df["Flag"].sum()) if not fuel_df.empty and "Flag" in fuel_df else 0

    summary = pd.DataFrame([
        {"Check": "AR match (QB vs Alvys)",   "Flags": ar_flags,   "Threshold": f"${AR_TOLERANCE_USD:.0f}"},
        {"Check": "AP match (QB vs Ramp)",    "Flags": ap_flags,   "Threshold": f">{AP_RAMP_LAG_DAYS}d not in QB"},
        {"Check": "Fuel match (QB vs Comdata)","Flags": fuel_flags, "Threshold": f"${FUEL_TOLERANCE_USD:.0f}/mo"},
    ])

    out_path = Path("output/reconciliation/Recon_Master.xlsx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary.to_excel(writer,  sheet_name="Summary",       index=False)
        ar_df.to_excel(writer,    sheet_name="AR_Match",      index=False)
        ap_df.to_excel(writer,    sheet_name="AP_Match",      index=False)
        fuel_df.to_excel(writer,  sheet_name="Fuel_Match",    index=False)

    ensure_folder(graph_token, upn, "Reconciliation")
    upload_file(graph_token, upn,
                "Reconciliation/Recon_Master.xlsx", out_path.read_bytes())
    log.info("Recon complete — AR:%d AP:%d Fuel:%d flags ✓", ar_flags, ap_flags, fuel_flags)


if __name__ == "__main__":
    main()
```

### Workflow: `.github/workflows/accounting_recon.yml`

```yaml
# Accounting reconciliation — runs at 9am CT daily, after all sources have run.
# QB, Ramp, Comdata must complete first (their earliest runs are 4am CT).
# Trigger: workflow_call from refresh_all.yml after all source workflows finish.
name: Accounting Reconciliation (daily 9am CT)
on:
  workflow_dispatch:
  workflow_call:
  schedule:
    - cron: '0 14 * * *'    # 9am CDT / 8am CST (gate confirms)
    - cron: '30 14 * * *'   # 9:30am backup
    - cron: '0 15 * * *'    # 10am CST primary
jobs:
  reconcile:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - name: Gate to 9-10am CT
        id: ct_gate
        if: github.event_name == 'schedule'
        run: |
          CT_HOUR=$(TZ=America/Chicago date +%-H)
          case "$CT_HOUR" in 9|10) echo "OK" ;; *) echo "skip=1" >> "$GITHUB_OUTPUT" ;; esac
      - uses: actions/checkout@v4
        if: steps.ct_gate.outputs.skip != '1'
      - uses: actions/setup-python@v5
        if: steps.ct_gate.outputs.skip != '1'
        with: { python-version: '3.11', cache: pip }
      - run: pip install -r requirements.txt
        if: steps.ct_gate.outputs.skip != '1'
      - name: Run reconciliation
        if: steps.ct_gate.outputs.skip != '1'
        env:
          AZURE_TENANT_ID:     ${{ secrets.AZURE_TENANT_ID }}
          AZURE_CLIENT_ID:     ${{ secrets.AZURE_CLIENT_ID }}
          AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
          ONEDRIVE_USER_UPN:   ${{ secrets.ONEDRIVE_USER_UPN }}
        run: python -m src.accounting_reconciliation
```

---

## 7. Optional: SQLite Audit Log

The existing OneDrive Excel pattern covers Power BI well. Add a SQLite audit log **only if** you need:
- SQL queries over multi-month history (Power BI keeps only current snapshot)
- Audit trail of who approved what in Ramp
- Reconciliation trend tracking over time

If you do want it, keep it as a `.db` file committed to a private repo or stored in OneDrive — no hosted database required.

### Schema (SQLite DDL)

```sql
-- One row per pipeline run — used for trend/anomaly analysis
CREATE TABLE pipeline_runs (
    run_id      TEXT PRIMARY KEY,   -- ISO timestamp + source: '2026-06-19T09:00_ramp'
    source      TEXT NOT NULL,      -- 'ramp' | 'comdata' | 'triumph' | 'recon'
    run_at      TEXT NOT NULL,      -- ISO 8601 UTC
    rows_loaded INTEGER,
    errors      INTEGER DEFAULT 0,
    notes       TEXT
);

-- Reconciliation flag history
CREATE TABLE recon_flags (
    flag_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,      -- YYYY-MM-DD
    check_name  TEXT NOT NULL,      -- 'AR_match' | 'AP_match' | 'Fuel_match'
    entity_key  TEXT,               -- customer name / vendor name / month
    source_a    REAL,               -- QB amount
    source_b    REAL,               -- Alvys/Ramp/Comdata amount
    variance    REAL,
    flagged     INTEGER DEFAULT 0,  -- 1 if above threshold
    resolved_at TEXT                -- NULL until someone clears it
);

-- AP bills not entered in QB
CREATE TABLE ap_gaps (
    bill_id         TEXT PRIMARY KEY,   -- Ramp BillId
    vendor_name     TEXT,
    invoice_number  TEXT,
    invoice_date    TEXT,
    amount          REAL,
    first_seen      TEXT,               -- when we first noticed it missing
    last_checked    TEXT,
    resolved        INTEGER DEFAULT 0
);

-- Intercompany balance check
CREATE TABLE intercompany_check (
    check_date   TEXT NOT NULL,
    payable_entity   TEXT,   -- e.g. 'X-Trux Inc'
    receivable_entity TEXT,  -- e.g. 'Truk-Way Leasing'
    payable_balance  REAL,
    receivable_balance REAL,
    variance         REAL,
    flagged          INTEGER DEFAULT 0
);
```

**When to add this:** After Ramp + Comdata + Triumph are live and running cleanly for 30 days. The Excel snapshots give you current-day visibility; the SQLite adds trend depth.

---

## 8. Accounting Email Brief

The existing `financial_email.py` covers AR reconciliation and invoice closeout. Extend it — don't create a parallel report — by adding a **Reconciliation** section.

### Addition to `financial_email.py` (sketch)

```python
# After existing AR section, add:

def _recon_section(graph_token: str, upn: str) -> str:
    """Reconciliation flag summary — sourced from Recon_Master.xlsx."""
    try:
        raw = download_file(graph_token, upn, "Reconciliation/Recon_Master.xlsx")
        summary = pd.read_excel(raw, sheet_name="Summary")
        ap_gaps = pd.read_excel(raw, sheet_name="AP_Match")
        ap_gaps = ap_gaps[ap_gaps.get("Flag_NotInQB", pd.Series(False, index=ap_gaps.index))]
    except Exception:
        return ""   # fail-soft; don't break the brief

    flags_total = summary["Flags"].sum() if "Flags" in summary.columns else 0
    if flags_total == 0:
        badge = '<span style="color:#2e7d32">✓ All checks clear</span>'
    else:
        badge = f'<span style="color:#c62828">⚠ {flags_total} reconciliation gaps</span>'

    rows = ""
    for _, row in summary.iterrows():
        color = "#c62828" if row["Flags"] > 0 else "#2e7d32"
        rows += (
            f"<tr><td>{row['Check']}</td>"
            f"<td style='color:{color};font-weight:bold'>{row['Flags']}</td>"
            f"<td>{row['Threshold']}</td></tr>"
        )

    ap_rows = ""
    if not ap_gaps.empty:
        for _, b in ap_gaps.head(10).iterrows():
            ap_rows += (
                f"<tr><td>{b.get('VendorName','')}</td>"
                f"<td>{b.get('InvoiceNumber','')}</td>"
                f"<td>${float(b.get('AmountTotal',0)):,.2f}</td>"
                f"<td>{b.get('AgeDays','?')} days</td></tr>"
            )

    return f"""
    <h3>Reconciliation Status {badge}</h3>
    <table border="1" cellpadding="4" style="border-collapse:collapse;font-size:12px">
      <tr><th>Check</th><th>Gaps</th><th>Threshold</th></tr>
      {rows}
    </table>
    {'<h4 style="color:#c62828">Bills in Ramp not yet entered in QB</h4>' if ap_rows else ''}
    {'<table border="1" cellpadding="4" style="border-collapse:collapse;font-size:12px"><tr><th>Vendor</th><th>Invoice #</th><th>Amount</th><th>Age</th></tr>' + ap_rows + '</table>' if ap_rows else ''}
    """
```

---

## 9. Karpathy Wiki Hooks

The `karpathy_compile.yml` action runs `src/karpathy_writer.py` on the wiki pages. After the reconciliation run, append a structured daily metrics row so Phase 2 KPI trends have a clean time-series.

### `src/karpathy_daily_metrics.py` (new, ~80 lines)

```python
"""Append one row of key metrics to Karpathy-Wiki/wiki/daily-metrics.csv
after each reconciliation run. Consumed by Phase 2 weekly decision brief."""
import csv, datetime, os
from pathlib import Path
import pandas as pd
from .onedrive_upload import download_file, get_token

METRICS_FILE = Path("Karpathy-Wiki/wiki/daily-metrics.csv")

HEADERS = [
    "date",
    "ar_total_qb",        # QB total open AR across X-Trux + X-Linx
    "ar_flags",           # AR reconciliation gaps count
    "ap_gaps_count",      # Bills in Ramp not yet in QB
    "ap_gaps_amount",     # Dollar value of those gaps
    "fuel_variance",      # Comdata vs QB fuel variance this month
    "recon_flags_total",  # All reconciliation flags combined
]


def append_metrics(graph_token: str, upn: str) -> None:
    try:
        raw = download_file(graph_token, upn, "Reconciliation/Recon_Master.xlsx")
        summary = pd.read_excel(raw, sheet_name="Summary")
        ap_gaps = pd.read_excel(raw, sheet_name="AP_Match")
        ap_gaps_flagged = ap_gaps[ap_gaps.get("Flag_NotInQB", False)] if not ap_gaps.empty else pd.DataFrame()
    except Exception:
        return   # fail-soft

    today = str(datetime.date.today())
    row = {
        "date":              today,
        "ar_flags":          int(summary.loc[summary["Check"].str.contains("AR"), "Flags"].sum()) if not summary.empty else 0,
        "ap_gaps_count":     len(ap_gaps_flagged),
        "ap_gaps_amount":    float(pd.to_numeric(ap_gaps_flagged.get("AmountTotal", pd.Series()), errors="coerce").sum()) if not ap_gaps_flagged.empty else 0,
        "recon_flags_total": int(summary["Flags"].sum()) if not summary.empty and "Flags" in summary.columns else 0,
    }

    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not METRICS_FILE.exists()
    with open(METRICS_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)
```

**Auto-flag risk register:** In `accounting_recon.main()`, after writing the Excel, call `karpathy_writer` with a structured log entry when flags exceed thresholds:

```python
# After reconciliation runs:
if ap_flags > 5 or ap_gaps_amount > 5000:
    from .karpathy_writer import append_risk_note
    append_risk_note(
        risk_id="AP-ENTRY-LAG",
        note=f"{today}: {ap_flags} Ramp bills (${ap_gaps_amount:,.0f}) not yet in QB",
    )
```

---

## 10. Required GitHub Secrets (New)

Add these to the `jeffxtrux-svg/alvys-pipeline` repo settings:

| Secret | Value | Notes |
|---|---|---|
| `RAMP_CLIENT_ID` | Ramp Developer App client ID | Settings → Developers → Applications |
| `RAMP_CLIENT_SECRET` | Same app | Mark as sensitive |
| `COMDATA_SFTP_HOST` | e.g. `sftp.comdata.com` | Confirm with Comdata account rep |
| `COMDATA_SFTP_USER` | Comdata portal username | |
| `COMDATA_SFTP_KEY` | Base64-encoded SSH private key | `base64 -i ~/.ssh/comdata_rsa` |
| `COMDATA_SFTP_PATH` | `/reports/` or account-specific | |
| `TRIUMPH_API_KEY` | Triumph carrier portal | Skip if not factoring |
| `TRIUMPH_COMPANY_ID` | Triumph account/carrier ID | |

**Existing secrets that new connectors reuse (no changes needed):**
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `ONEDRIVE_USER_UPN`

---

## 11. pip Dependencies (addendum to `requirements.txt`)

```text
# Existing (already in requirements.txt):
#   pandas, openpyxl, requests, python-dotenv

# Add for new connectors:
paramiko>=3.4.0     # Comdata SFTP
```

Triumph and Ramp are REST APIs — no new deps beyond `requests` (already present).

---

## 12. Implementation Roadmap

### Phase A — Ramp connector (1–2 days)
1. Create Ramp Developer App → get `RAMP_CLIENT_ID` / `RAMP_CLIENT_SECRET`
2. Write `src/ramp_client.py` + `src/ramp_main.py` from scaffold above
3. Add `ramp_refresh.yml` workflow
4. Add Ramp secrets to GitHub
5. Test with `workflow_dispatch` → verify `Ramp/Ramp_Master.xlsx` in OneDrive
6. Connect Ramp Bills sheet to Power BI; add AP pivot to financial brief

### Phase B — Reconciliation engine (2–3 days)
1. Write `src/accounting_reconciliation.py` from scaffold above
2. Add `accounting_recon.yml` workflow (runs after QB + Ramp)
3. Add Recon_Master.xlsx to Power BI as a new data source
4. Add `_recon_section()` to `financial_email.py`
5. Test: manually force a Ramp bill entry lag + confirm it shows in email

### Phase C — Comdata fuel cards (2–3 days)
1. Get Comdata SFTP credentials from Comdata portal or account rep
2. Install `paramiko` and add to `requirements.txt`
3. Write `src/comdata_client.py` + `src/comdata_main.py` from scaffold above
4. Add `comdata_refresh.yml` workflow (2×/day)
5. Add fuel cross-reference Power BI page (Comdata vs Samsara vs QB)

### Phase D — Triumph factoring (1–2 days, only if factoring)
1. Enroll in Triumph Partner Portal → get API key
2. Confirm API endpoints with Triumph (the `BASE_URL` in spec is an estimate)
3. Write `src/triumph_main.py` (follows same pattern as `ramp_main.py`)
4. Add factoring tab to financial brief: advance %, reserve balance, net cash position

### Phase E — SQLite audit log (1 day, optional)
1. Only if you want trend queries beyond what Power BI holds
2. Store `.db` in a private OneDrive folder; download/update/upload each run
3. Add `karpathy_daily_metrics.py` to write daily metrics CSV for Phase 2 KB

---

## Appendix: Ramp API — Confirmed Endpoints

Base: `https://api.ramp.com/developer/v1`

| Endpoint | Method | Use |
|---|---|---|
| `/token` | POST | OAuth2 client_credentials |
| `/bills` | GET | All AP bills — paginated |
| `/bills/{id}` | GET | Single bill detail |
| `/transactions` | GET | Card transactions — paginated |
| `/transactions/{id}` | GET | Single transaction |
| `/vendors` | GET | Vendor list |
| `/users` | GET | Cardholders |
| `/departments` | GET | Department structure |
| `/receipts` | GET | Receipt metadata |

Pagination: `page_size` + `start` cursor from `page.next` in response.
Rate limits: 100 req/min; pipeline stays well under at 3×/day.

---

## Appendix: Power BI Changes Needed

When Ramp + Comdata + Recon sources are live, add to the existing `.pbix`:

1. **New data sources:** `OneDrive/Ramp/Ramp_Master.xlsx`, `OneDrive/Comdata/Comdata_Master.xlsx`, `OneDrive/Reconciliation/Recon_Master.xlsx`
2. **Relationships:**
   - `Ramp[VendorName]` ↔ `QB_AgedPayableDetail[Vendor]` (many-to-one, normalized)
   - `Comdata[UnitNumber]` ↔ `Samsara Master[Vehicles][name]` (after `_clean_vehicle_name`)
3. **New report pages:**
   - **AP Pipeline** — Ramp bills by vendor + age (open / approved / paid), flagged if not in QB
   - **Fuel Analysis** — Comdata by unit + driver vs Samsara fuel telemetry; QB GL variance
   - **Reconciliation** — daily flag counts trending, AP gap list
4. **Update existing AR page:** drive from `Recon_Master[AR_Match]` instead of manual QB pulls
