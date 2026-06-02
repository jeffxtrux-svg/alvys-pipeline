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
        src.sambasafety_main  (daily 10:30 UTC)
            ├── download_file × 2     (Graph)
            ├── combine_to_workbook   (sambasafety_combine.py)
            └── upload_file
                                 │
                                 ▼
                      OneDrive/SambaSafety/
                          SambaSafety_Master.xlsx
                                 │
                                 ▼
       src.scorecard_email  (daily 11:30 UTC, 60 min later)
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

## The two source reports

You schedule both inside the SambaSafety admin UI to email
`jeff@xfreight.net` daily:

| SambaSafety report | What it carries | Becomes |
|--------------------|-----------------|---------|
| **Overview → Risk Index Report** | one row per monitored driver: name, license #, license status, expiration, state, current risk index score, score bucket (Clean / Activity / Exception) | `risk_index_report.csv` → `Drivers` sheet |
| **MVR Activity → Violations** | one row per violation: driver, date, violation type, points/score, severity | `violationsReport.csv` → `Violations` sheet |

Both CSV filenames are configurable via env (`SAMBASAFETY_RISK_INDEX_FILE` /
`SAMBASAFETY_VIOLATIONS_FILE`) but defaults match what SambaSafety's
report exporter writes by default.

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

## Daily refresh job (`sambasafety_refresh.yml`)

- **Cron:** `30 10 * * *` UTC → **4:30am CST** (winter) / **5:30am CDT**
  (summer). One hour ahead of the scorecard so the workbook is fresh.
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
3. **SambaSafety API (future).** Long-term replacement. When wired,
   `sambasafety_main.py` will be replaced with a `sambasafety_client.py`
   that pulls directly — no CSV step, no OneDrive intermediate. The
   downstream contract (`SambaSafety_Master.xlsx` with `Drivers` +
   `Violations` sheets) stays the same so nothing else needs to change.

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

## See also

- [operations.md § Scorecard email runbook](./operations.md) — debugging
  recipes for the preflight block (including `MISSING  SambaSafety
  Master` and `absent  SambaSafety Master (optional)`).
- [onedrive-and-alerts.md](./onedrive-and-alerts.md) — Azure app /
  Graph permissions shared with this job.
- [automation-and-secrets.md](./automation-and-secrets.md) — full
  secret table.
