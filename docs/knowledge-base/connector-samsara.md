# Connector: Samsara (telematics)

Samsara is the fleet/telematics source: where the trucks are, how they're being
driven, inspections, and fuel-tax data. Unlike Alvys it doesn't match a legacy
schema, so the transform is generic (`json_normalize`) and each data type gets
its own sheet.

- **Entry point:** `python -m src.samsara_main`
- **Output:** `output/samsara/Samsara_Master.xlsx` — one sheet per data type
- **Files:** `samsara_main.py`, `samsara_client.py`, `samsara_alerts.py`

## Authentication

A **static, long-lived API token** (`SAMSARA_API_TOKEN`), generated in the
Samsara dashboard (Settings → API Tokens). It's sent in the `Authorization`
header on every request.

> ⚠️ **Header gotcha:** the code currently sends `Authorization: Bearer
> <token>` (`samsara_client.py::_headers`). The module's *docstring* still says
> "Token (NOT Bearer)" — that comment is **stale**; a commit switched it to
> `Bearer` to match the current Samsara API. Trust the code. If you ever get
> 401s across the board, the `Token` vs `Bearer` scheme is the first thing to
> check (and update the docstring while you're there).

- API base: `https://api.samsara.com`

## Pagination

Cursor-based (`_get_pages`): read `data` from the response, then follow
`pagination.endCursor` into the `after` query param while
`pagination.hasNextPage` is true. Page size `limit=512`, 0.1s between pages.
`_safe_get` wraps this to return `[]` on any HTTP error instead of raising — so
a missing scope on the token degrades one data type to empty rather than killing
the whole run.

## What it fetches (the 10 steps)

`samsara_main.py` runs these in order, then flattens each to a sheet:

| # | Method | Endpoint(s) | Notes |
|---|--------|-------------|-------|
| 1 | `fetch_vehicles` | `/fleet/vehicles` | roster; also supplies vehicle IDs for trips |
| 2 | `fetch_drivers` | `/fleet/drivers` | roster |
| 3 | `fetch_vehicle_stats` | `/fleet/vehicles/stats` | **2 calls merged** (see below) |
| 4 | `fetch_locations` | `/fleet/vehicles/locations` | current GPS |
| 5 | `fetch_trips` | `/fleet/vehicles/{id}/trips` | **per-vehicle** loop |
| 6 | `fetch_safety_events` | `/fleet/safety/events` → `/safety/events` | first path that returns data |
| 7 | `fetch_hos_logs` | `/fleet/hos/logs` → `/fleet/drivers/hos-logs` | duty-status **logs** (30-day window) |
| 8 | `fetch_hos_violations` | `/fleet/hos/violations` (+ 2 fallbacks) | actual **violations** (not logs); ~190-day window |
| 9 | `fetch_dvirs` | `POST /fleet/dvirs` | inspections; **POST, not GET** |
| 10 | `fetch_ifta` | tries 3 IFTA paths | last 3 months, one sheet each |

Three **time windows** are used: a long window (default 90 days, via
`SAMSARA_DAYS_BACK`) for trips; a separate ~190-day window
(`SAMSARA_SAFETY_DAYS_BACK`) for safety events / DVIRs / HOS violations so the
scorecard's "previous 6 months" view has history; and a fixed 30-day window for
HOS logs.

### Derived / cleaned sheets

`json_normalize` can't flatten nested arrays, so two data types get post-processed:

- **`DVIR_Defects`** — one row per defect (`Unit, Driver, Defect, Resolved,
  Reported, …`), exploded from the `defects[]` array (same field shape
  `samsara_alerts.py` reads). The raw `DVIRs` sheet is still written too.
- **`SafetyEvents`** gains clean `Event Type` / `Severity` / `Driver Name` /
  `Unit` columns decoded from the `behaviorLabels[]` array; `HOS_Violations`
  gains `Driver Name` / `Violation Type`. Timestamps are normalized from
  epoch-ms or ISO via `_ts_to_str`.

### Gotchas worth knowing

- **Vehicle stats — 4-type limit.** Samsara caps `types` at 4 per request, so
  `fetch_vehicle_stats` makes two calls (`obdOdometerMeters, fuelPercents,
  engineStates, gpsOdometerMeters` then `syntheticEngineSeconds`) and merges
  them by vehicle `id`.
- **Trips are per-vehicle.** The trips endpoint requires a vehicle ID in the
  path, so the client loops every vehicle ID and stamps each trip with its
  `vehicleId`.
- **DVIRs use POST.** Per Samsara API v2025.10, `GET /fleet/dvirs` is not
  allowed; `fetch_dvirs` posts the time range and cursors via a `after` field in
  the request body.
- **Endpoint fallback.** Safety, HOS, and IFTA each try a list of candidate
  paths and keep the first that returns rows — Samsara has moved these around.

## Transform & write — `samsara_main.py`

- `flatten()` runs `pandas.json_normalize(records, max_level=4)`; on failure it
  falls back to a plain `DataFrame(records)`.
- `_sanitize_df()` strips ASCII control characters (except tab/LF/CR) that
  openpyxl refuses to write into a cell.
- Sheet names are truncated to Excel's 31-char limit. Empty data types still get
  a placeholder sheet so the file structure is stable for Power BI.

## The alert system — `samsara_alerts.py`

A separate job (`python -m src.samsara_alerts`, also a step in the Samsara
workflow) that **emails maintenance** when it finds problems. It does **not**
write Excel — it's a notification path.

It checks two things:

1. **Active OBD fault codes (DTCs).** Reads
   `/fleet/vehicles/stats?types=nativeObdDtcCodes` and extracts any vehicle with
   active DTC IDs.
2. **Unresolved DVIR defects** in the last 7 days.

If either is found, it builds an HTML table and sends mail via **Microsoft Graph
`/users/{from}/sendMail`**, reusing `onedrive_upload.get_token` for the token.

- Env: `SAMSARA_API_TOKEN`, `AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET`,
  `ALERT_FROM_UPN` (default `jeff@xfreight.net`), `ALERT_TO_EMAILS`
  (comma-separated; defaults to the from address).
- **One-time Azure setup:** the app registration needs the **`Mail.Send`**
  Application permission (with admin consent) *in addition to*
  `Files.ReadWrite.All`. Without it, the job logs the issues but can't email.
- If Azure creds are absent, it logs the issues and exits 0 — never blocks the
  data refresh.

## Common tasks

- **Pull a longer history** → set `SAMSARA_DAYS_BACK` (trips) and/or
  `SAMSARA_SAFETY_DAYS_BACK` (safety / DVIR / HOS violations, default 190).
- **A data type is empty** → almost always an API-token scope problem; the log
  line `GET … → HTTP 4xx — skipping (check API token scope)` tells you which.
- **Alerts not arriving** → confirm `Mail.Send` consent and that
  `ALERT_TO_EMAILS` is set as a secret.
