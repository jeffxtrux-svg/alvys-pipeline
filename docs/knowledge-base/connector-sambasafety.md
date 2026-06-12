# SambaSafety connector

SambaSafety is the fourth data source in the pipeline. It is **not a
real-time API integration** today — instead, it follows a CSV-drop pattern:
two scheduled reports from SambaSafety land in OneDrive, a daily GitHub
Actions job merges them into a two-sheet workbook, and the executive brief
reads that workbook on page 2 (the SAFETY section's lead page).

Why the CSV bridge? SambaSafety's MVR product emits the data we need as
two separate scheduled reports rather than a single API. Until we wire up
the real API, the bridge gives us the same end-state — a single, fresh
`SambaSafety_Master.xlsx` in OneDrive every morning — without coupling
the scorecard to the export tool of the day.

## Data flow

```
SambaSafety   ──email──▶  jeff@xfreight.net
   (2 CSVs)                      │
                                 ▼
                          Power Automate
                          (or manual drop)
                                 │
                                 ▼
                      OneDrive/SambaSafety/
                       ├── risk_index_report.csv
                       └── violationsReport.csv
                                 │
                  ┌──────────────┘
                  ▼
        src.sambasafety_main  (daily 7:30 UTC)
            ├── download_file × 2     (Graph)
            ├── combine_to_workbook   (sambasafety_combine.py)
            └── upload_file
                                 │
                                 ▼
                      OneDrive/SambaSafety/
                          SambaSafety_Master.xlsx
                                 │
                                 ▼
       src.scorecard_email  (daily 8:30 UTC, 60 min later)
           ├── compute_sambasafety    →  monitored / license_issues /
           │                             high_risk / violations / ranked
           ├── page_strips[2]         (real-data callout above page 2)
           ├── action_items           (CDL EXPIRED / MVR HIGH RISK cards)
           ├── bottom_line            ("L licenses expiring within 30d…")
           └── build_page9            (page 2 — the SambaSafety page itself)
```

Page numbering: the SambaSafety page is **page 2** in the scorecard email
(SAFETY leads the detail section). The build function is still named
`build_page9` for stability — the `_header(..., pg=2, ...)` argument is
what controls the rendered page number.

## The three source reports

You schedule all three inside the SambaSafety admin UI to email
`jeff@xfreight.net` daily (the CSA scorecard is optional but adds page 10
of the brief when present):

| SambaSafety report | What it carries | Becomes |
|--------------------|-----------------|---------|
| **Overview → Risk Index Report** | one row per monitored driver: name, license #, license status, expiration, state, current risk index score, score bucket (Clean / Activity / Exception) | `risk_index_report.csv` → `Drivers` sheet |
| **MVR Activity → Violations** | one row per violation: driver, date, violation type, points/score, severity | `violationsReport.csv` → `Violations` sheet |
| **Invalid License Report** (optional) | one row per driver whose license SambaSafety has flagged invalid: status (DISQUALIFIED / SUSPENDED…), latest state action + date, MVR date, license #/state/type | `InvalidLicenseReport.csv` → `Invalid Licenses` sheet **+ status overlay onto the Drivers sheet** |
| **CSA2010 Preview Scorecard** (optional) | one row per FMCSA BASIC category for X-Trux's DOT: percentile rank, BASIC measure, segment violations, relevant inspections, snapshot date | `CSA2010 Preview Scorecard.csv` → `CSA Scorecard` sheet |

Filenames are configurable via env (`SAMBASAFETY_RISK_INDEX_FILE`,
`SAMBASAFETY_VIOLATIONS_FILE`, `SAMBASAFETY_INVALID_FILE`,
`SAMBASAFETY_CSA_FILE`) but defaults match
what SambaSafety's report exporter writes by default. The CSA and
Invalid License files are **fail-soft**: if the download 404s,
`sambasafety_main` logs a warning and writes the workbook without that
sheet — the scorecard brief still renders, just with a "data
unavailable" page 10 (CSA) or no invalid-license section (Invalid).

### Why the Invalid License Report gets a status overlay

The Risk Index export **lags state actions** — observed 2026-06: a driver
DISQUALIFIED on 05/22 still showed `License Status = VALID` in
`risk_index_report.csv` three weeks later, while `InvalidLicenseReport.csv`
carried the DISQUALIFICATION. So `combine_to_workbook` stamps the invalid
report's status onto matching `Drivers` rows (matched by normalized
license number — leading zeros stripped — falling back to full name).
`compute_sambasafety` applies the same override at read time as
belt-and-suspenders. An invalid license:

- forces the driver into page 2's **License status · action needed** table,
- renders a dedicated red **Invalid / disqualified licenses** table at the
  top of page 2 with the state action and dates,
- fires a `bad` **CDL DISQUALIFIED · NAME** action card on page 1 (these
  drivers are excluded from the generic CDL EXPIRED card so the wording
  stays accurate),
- adds an URGENT per-driver sentence to the page-1 bottom line, and
- prepends an `N license(s) INVALID/DISQUALIFIED` bit to the page-2 strip.

## The column re-mapping (`src/sambasafety_combine.py`)

`combine_to_workbook(risk_csv, violations_csv) → bytes` does the work.
The mappings exist so that `compute_sambasafety` (in `scorecard_email.py`)
sees the column names and bucket labels it expects, regardless of how
SambaSafety happens to format the export today.

### Risk Index → `Drivers` sheet

| Source column (any of) | Target column | Notes |
|------------------------|---------------|-------|
| `First Name` + `Last Name` (or any `Driver Name`/`Full Name`) | `Driver Name` | concatenated |
| `Current Risk Index Score` (or any `Risk Score`) | `Risk Score` | numeric |
| `Risk Index Score Category` ("Clean" / "Activity" / "Exception") | `Risk Category` | re-mapped to **Low / Medium / High** so the scorecard's string-based "high risk" detector fires |
| `License Number` / `License #` | `License Number` | verbatim |
| `License Status` | `License Status` | verbatim — "Active" / "Valid" / "OK" pass the `_LICENSE_OK` check |
| `License Expiration` (or `Expiration Date`) | `License Expiration` | parsed to date |
| `License State` / `Issuing State` | `License State` | verbatim |

### Violations → `Violations` sheet

| Source column | Target column | Notes |
|---------------|---------------|-------|
| `Driver Name` | `Driver Name` | |
| `Violation Date` (or `Conviction Date` / `Offense Date`) | `Date` | parsed |
| `Violation Description` (or `Violation` / `Offense`) | `Type` | verbatim |
| `Violation Score` (or `Points`) | `Points` | numeric |
| `State` / `Jurisdiction` | `State` | verbatim |
| *derived from score* | `Severity` | `≥8 → Major`, `4-7 → Moderate`, `<4 → Minor` |

`compute_sambasafety` then fuzzy-matches on column names (`_find_col`
walks a list of candidate spellings), so minor header variations are
non-breaking — but the **Low/Medium/High** label and the **Severity
thresholds** above are what the bucket / "high risk" logic keys on.

### CSA2010 Preview Scorecard → `CSA Scorecard` sheet

`_build_csa_scorecard` (in `sambasafety_combine.py`) parses the FMCSA
carrier scorecard CSV as-is — one row per BASIC category for the carrier
(DOT #841776 for X-Trux, Inc.). Columns the page-10 builder needs:

| Column | Purpose |
|--------|---------|
| `Category` (or `BASIC Category` / `BASIC`) | the BASIC name (Unsafe Driving, HOS Compliance, Maintenance, …); `*` suffixes are stripped before matching against the threshold table |
| `Percentile` (or `CSA Percentile` / `Rank`) | the carrier's percentile rank for that BASIC (0–100). Higher = worse. |
| `BasicMeasure` (or `Basic Measure` / `Measure`) | raw FMCSA BASIC measure score |
| `SegmentViolations` (or `Segment Violations` / `Violations`) | count of violations in the BASIC's measurement window |
| `RelevantInspections` (or `Relevant Inspections` / `Inspections`) | inspection sample size behind the percentile |
| `SnapshotDate` (or `Snapshot Date` / `Snapshot`) | FMCSA snapshot the row reflects |
| `DotNumber` (or `DOT Number` / `DOT`) | DOT # — pulled from the first row as page metadata |
| `AvgPowerUnits` (or `Avg Power Units` / `Power Units`) | carrier size — drives the `_CSA_INTERVENTION` threshold pick for size-sensitive BASICs |

No column is renamed; the page-10 builder fuzzy-matches the same
candidate-list pattern (`_find_col`) the other two sheets use, so a
SambaSafety header rename only requires updating the candidate list, not
a schema migration.

## Daily refresh job (`sambasafety_refresh.yml`)

- **Cron:** `30 7 * * *` UTC → **1:30am CST** (winter) / **2:30am CDT**
  (summer). One hour ahead of the scorecard primary slot (`30 8 UTC` =
  3:30am CDT) so the merged workbook is reliably present in OneDrive
  when the scorecard reads it.
- **Steps:** checkout → install requirements → `python -m src.sambasafety_main`
  → upload `output/sambasafety/` as a 7-day artifact.
- **Required secrets:** `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
  `AZURE_CLIENT_SECRET` (same Azure app as the rest of the pipeline,
  needs `Files.ReadWrite.All` consent).
- **Environment:** `ONEDRIVE_USER_UPN: jeff@xfreight.net` hardcoded in
  the workflow.
- **Optional env overrides:** `SAMBASAFETY_FOLDER` (default `SambaSafety`),
  `SAMBASAFETY_RISK_INDEX_FILE`, `SAMBASAFETY_VIOLATIONS_FILE`,
  `SAMBASAFETY_OUT_FILE`.

If either CSV is missing the job fails fast with a 404 on the Graph
download — open the OneDrive folder and confirm both files are there.
The scorecard email's preflight block will then log
`MISSING  SambaSafety Master` and the SambaSafety page will render with
"data not loaded this run". The scorecard does **not** fail on a missing
SambaSafety workbook — it's the only optional source.

## How the scorecard uses the data

After `compute_sambasafety` parses the workbook, the resulting dict
drives three things in `src/scorecard_insights.py`:

1. **`bottom_line()`** appends a sentence to the page-1 paragraph if
   anything is interesting: `Driver compliance: 2 licenses expiring within
   30d · 3 drivers high-risk per MVR (pg 2).`
2. **`action_items()`** can fire up to two SambaSafety cards:
   - `CDL EXPIRED · DRIVER NAME` (severity `bad`) if any license is past
     expiration or expires within 7 days — these belong above the
     coaching cards because an expired CDL grounds the truck.
   - `CDL RENEWALS UPCOMING` (severity `warn`) for the 30-day horizon.
   - `MVR HIGH RISK · N DRIVERS` (severity `warn`) if any drivers fall
     into the High risk bucket.
3. **`page_strips[2]`** renders a one-line callout above the SambaSafety
   page itself: `N drivers monitored · L license issues · H high-risk
   per MVR · V violations in last 365d. Worst risk: NAME (score).`

Tunable constants live at the top of `src/scorecard_email.py`:

| Constant | Meaning | Current value |
|----------|---------|---------------|
| `LICENSE_EXPIRY_WARN_DAYS` | window for "expiring soon" tile | 60 |
| `SAMBA_HIGH_RISK_SCORE` | score threshold when no category column | 16 |
| `VIOLATION_WINDOW_DAYS` | how far back to surface violations | 365 |

The 365-day window is intentional — SambaSafety violations are historical
MVR records, not real-time events.

### The CSA Scorecard report (page 10)

The third SambaSafety report drives **page 10 — CSA Carrier Scorecard**.
`compute_csa_scorecard` reads the `CSA Scorecard` sheet from
`SambaSafety_Master.xlsx` and produces:

```python
{
    "basics": [
        {"category": "Unsafe Driving", "percentile": 72.3, "measure": 1.84,
         "seg_violations": 23, "rel_inspections": 412,
         "threshold": 65, "intervention": True},
        ...
    ],
    "n_alert": 1,              # BASICs at/above their intervention threshold
    "worst":   { ... },        # the category with the highest percentile
    "snapshot_date":   "2026-05-23",
    "dot_number":      "841776",
    "avg_power_units": "67",
}
```

`build_csa_scorecard_page` renders four tiles (highest-risk BASIC,
intervention-alert count, DOT #, FMCSA snapshot date) and a table of all
BASICs sorted by percentile (worst first). Each row earns one of:

- **INTERVENTION LIKELY** (`bad`) — percentile ≥ the BASIC's FMCSA
  threshold (see `_CSA_INTERVENTION` below). FMCSA opens an intervention
  workflow at these percentile bands.
- **WATCH** (`warn`) — percentile ≥ 75% of the threshold; not yet
  intervention-eligible but trending there.
- **OK** (`good`) — comfortably below threshold.

#### FMCSA BASIC intervention thresholds

The `_CSA_INTERVENTION` table in `src/scorecard_email.py` encodes FMCSA's
[carrier-of-record intervention bands](https://csa.fmcsa.dot.gov/about/basics/csa-measures):

| BASIC category | Percentile alert threshold |
|----------------|---------------------------|
| Unsafe Driving | **65** |
| Crash Indicator | **65** |
| Maintenance | 80 |
| HOS Compliance | 80 |
| Hazardous Materials | 80 |
| Driver Fitness | 80 |
| Controlled Substances / Alcohol | 80 |

Unsafe Driving and Crash Indicator alert sooner because they correlate
most directly with public-safety risk; the rest follow the standard 80th
percentile cutoff for general carriers. The category-name match is a
case-insensitive substring lookup, so SambaSafety renames (e.g.
"HOS Compliance" → "Hours-of-Service Compliance") don't break the alert
gate; categories that don't match anything fall through to `80`.

#### Failing soft

- **CSA CSV missing from OneDrive.** `sambasafety_main._build_from_csv`
  catches the download exception and skips the CSA sheet. The page-10
  builder sees `csa = None` and renders a `WARN` callout asking the user
  to place `CSA2010 Preview Scorecard.csv` in `OneDrive/SambaSafety/`.
- **Header rename in the CSV.** Add the new spelling to the `_find_col`
  candidate list in `compute_csa_scorecard` (around line ~2894). All
  fields except `Category` are optional — a missing column degrades to an
  em-dash in that cell, not a crash.
- **Empty / single-row file.** If no row has a `Category` value the
  function returns `None` and the page renders the same "data unavailable"
  callout.

## Getting the source CSVs into OneDrive

You have three options. They produce the same outcome; pick by how
hands-on you want to be:

1. **Manual drop (today's default).** Open each daily email from
   `no-reply@sambasafety.com`, save the CSV attachments into
   `OneDrive/SambaSafety/`. ~1 min/day, no setup required, but **must
   happen before 4:30am CST** for the refresh job to pick them up.
2. **Power Automate flow (recommended).** Build a flow in
   `flow.microsoft.com` that watches `jeff@xfreight.net` for new mail
   from `no-reply@sambasafety.com` with attachments, then saves each
   attachment to `OneDrive/SambaSafety/`. Set up once, hands-free
   forever. The two CSV filenames stay consistent because the same
   SambaSafety report always emits the same filename.
3. **SambaSafety API (live).** Set `SAMBASAFETY_API_TOKEN` and the
   refresh job switches automatically to API mode — no CSV step, no
   OneDrive intermediate. See **"API mode"** below.

## API mode (zero-cost replacement of the CSV bridge)

When `SAMBASAFETY_API_TOKEN` is present in the workflow secrets,
`sambasafety_main.py` uses `src.sambasafety_client.SambaSafetyClient`
to assemble `SambaSafety_Master.xlsx` directly from REST endpoints.
**Same workbook schema** (`Drivers` + `Violations` sheets) — downstream
code is unchanged.

### Why this is free

SambaSafety's pricing is per **MVR order placed**, not per API call.
The client only calls **read** endpoints in the License Monitoring
family, plus reads from previously-placed MVRs (free to re-read):

| Endpoint | Purpose | Cost |
|---|---|---|
| `GET /organization/v1/groups` | discover group IDs | $0 |
| `GET /organization/v1/groups/{id}/people` | active driver roster | $0 |
| `GET /organization/v1/people/{id}/licenses` | license # / state / CDL flag | $0 |
| `GET /organization/v1/licenses/{id}/status` | VALID / SUSPENDED / EXPIRED | $0 |
| `GET /reports/v1/people/{id}/motorvehiclereports` | list existing MVRs | $0 |
| `GET /reports/v1/motorvehiclereports/{mvrId}` | read MVR content (expiration, violations, risk) | $0 |

We never call any `POST /orders/...` endpoint, so we never trigger a
fresh state pull and never pay a state fee. License expiration + risk
score + violations all come from the **most recent existing MVR per
driver**.

### Configuration

| Env / secret | Required | Default |
|---|---|---|
| `SAMBASAFETY_API_TOKEN` | yes (enables API mode) | — |
| `SAMBASAFETY_API_BASE_URL` | no | `https://api.sambasafety.io` (prod). Use `https://api-demo.sambasafety.io` for the demo environment. |
| `SAMBASAFETY_AUTH_SCHEME` | no | `bearer` (default — for JWT tokens like `eyJ…`, sent as `Authorization: Bearer <token>`). Set to `apikey` if SambaSafety gave you a non-JWT key, which goes in `X-Api-Key`. |
| `SAMBASAFETY_GROUP_NAME` | no | empty = all groups merged. Case-insensitive substring match. Set when you only want one group's drivers in the scorecard (e.g. `X-Trux`). |

**Auth note:** The JWT in the envelope file (anything starting with
`eyJhbGciOiJIUzI1NiJ9.…`) is a bearer token, not an API key. Send it
as `Authorization: Bearer <jwt>` — that's the default. SambaSafety's
Postman collection defaults to `X-Api-Key` because they also issue
non-JWT keys to some customers, but for JWT tokens that header will
return HTTP 403.

### Falling back

If `SAMBASAFETY_API_TOKEN` is empty or missing, the script reverts to
the CSV-drop path automatically — no errors, no special handling. So
you can roll back to CSV by simply deleting the secret.

## When you most commonly edit something

- **Page 2 strip / bottom-line wording.** `src/scorecard_insights.py`
  — `page_strips()` for the strip, `bottom_line()` for the paragraph
  sentence, `action_items()` for the cards.
- **A column comes back blank on the SambaSafety page.** SambaSafety
  renamed a field. Add the new spelling to the candidate list in
  `compute_sambasafety`'s `_find_col` calls (lines ~2178-2184) — or
  remap it at the source in `sambasafety_combine.py`.
- **Score buckets need re-tuning.** `CLEAN_MAX` / `ACTIVITY_MAX` in
  `sambasafety_combine.py` define the Clean/Activity/Exception →
  Low/Medium/High mapping. Severity thresholds for violations live in
  the same module.
- **Adding a third SambaSafety report.** Drop the CSV alongside the
  other two, parameterize a new env var, extend `combine_to_workbook`
  to produce a third sheet, then have `compute_sambasafety` consume it.
  The downstream contract is flexible — page 2 reads whatever
  `compute_sambasafety` returns.

## DOT medical card / DOT physical — comes from Alvys, not SambaSafety

SambaSafety's Risk Index Report carries license expirations but **not**
DOT medical-card expirations. The scorecard's page 2 covers both anyway
by reading the Alvys Drivers feed:

- The Alvys pipeline (`src/main.py`) writes a `Drivers` sheet into
  `Alvys Pipeline.xlsx` using `LicenseExpiresAt` + `MedicalExpiresAt`
  from each driver record.
- `compute_alvys_drivers` in the scorecard reads that sheet, filters to
  active drivers (Status not Inactive, `TerminatedAt` is null), and
  buckets each into 30-day pipeline / 14-day critical windows for both
  CDL and DOT medical card.
- Page 2 renders the `DOT medical card · expirations within 30d` table
  under the SambaSafety blocks. Bottom-line gets per-driver sentences
  for anything inside the 14-day window. Action items fire `DOT MEDICAL
  CARD · NAME` (bad) for the 7-day critical window.

Full details (which Alvys fields, which sheet schema) in
[connector-alvys.md § Drivers sheet](./connector-alvys.md).

## See also

- [operations.md § Scorecard email runbook](./operations.md) — debugging
  recipes for the preflight block (including `MISSING  SambaSafety
  Master` and `absent  SambaSafety Master (optional)`).
- [onedrive-and-alerts.md](./onedrive-and-alerts.md) — Azure app /
  Graph permissions shared with this job.
- [automation-and-secrets.md](./automation-and-secrets.md) — full
  secret table.
- [connector-alvys.md](./connector-alvys.md) — the Drivers sheet
  (CDL + DOT medical card) feed.
