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
| 5 | `fetch_trips` | `/v1/fleet/trips` (legacy v1) | **per-vehicle** loop; singular `vehicleId` + ms timestamps; response not in `data` envelope (read from `trips`/`vehicleTrips`/`vehicles[].trips`) |
| 6 | `fetch_safety_events` | `/fleet/safety-events` | hyphen, not slash; `limit` capped at 200 |
| 7 | `fetch_hos_logs` | `/fleet/hos/logs` → `/fleet/drivers/hos-logs` | duty-status **logs** (30-day window) |
| 8 | `fetch_hos_violations` | `/fleet/hos/violations` (+ 2 fallbacks) | actual **violations** (not logs); ~190-day window |
| 9 | `fetch_dvirs` | **GET** `/fleet/dvirs/history` | inspections; paged in **≤30-day chunks** |
| 10 | `fetch_ifta` | `/fleet/reports/ifta/vehicle` (singular) | `year` (int) + `month` as full name; current month 400s with "data may still be processing" (~72-hour lag) |

Three **time windows** are used: a long window (default 90 days, via
`SAMSARA_DAYS_BACK`) for trips; a separate ~190-day window
(`SAMSARA_SAFETY_DAYS_BACK`) for safety events / DVIRs / HOS violations so the
scorecard's "previous 6 months" view has history; and a fixed 30-day window for
HOS logs.

### Derived / cleaned sheets

`json_normalize` can't flatten nested arrays, so two data types get post-processed:

- **`DVIR_Defects`** — one row per defect (`Unit, Driver, Defect, Resolved,
  Reported, …`), exploded from each DVIR's `vehicleDefects[]` / `trailerDefects[]`
  arrays (the current `/fleet/dvirs/history` shape; the older `defects[]`
  fallback is still tried). `Resolved` reads `isResolved` (falling back to
  `resolved`). `Reported` prefers the defect's own `createdAtTime` and falls
  back to the DVIR's `startTime` — the DVIR record itself doesn't carry
  `createdAt*`, so without this fallback every defect's date came out null.
- **`SafetyEvents`** gains clean `Event Type` / `Severity` / `Driver Name` /
  `Unit` columns decoded from the `behaviorLabels[]` array; `HOS_Violations`
  gains `Driver Name`, `Violation Type`, **and an explicit `violationStartTime`
  column** (json_normalize doesn't always surface that nested field). Timestamps
  are normalized from epoch-ms or ISO via `_ts_to_str`.

### Gotchas worth knowing

- **Vehicle stats — 4-type limit.** Samsara caps `types` at 4 per request, so
  `fetch_vehicle_stats` makes two calls (`obdOdometerMeters, fuelPercents,
  engineStates, gpsOdometerMeters` then `syntheticEngineSeconds`) and merges
  them by vehicle `id`.
- **Trips: legacy v1, per-vehicle.** Lives at `/v1/fleet/trips` (the `/v1/` prefix
  is required — `/fleet/trips` returns 404). Each call takes a **singular**
  `vehicleId` query param (CSV `vehicleIds` returns 400 "Missing parameter:
  vehicleId"), plus `startMs`/`endMs`. The response **doesn't use the standard
  `{"data": [...]}` envelope**, so `fetch_trips` does a direct GET and pulls
  trips from `trips` / `vehicleTrips` / `vehicles[].trips`.
- **DVIRs are GET, paged in ≤30-day chunks.** `POST /fleet/dvirs` is the
  *create* endpoint and returns `401 "requires DVIRs write permissions"`. The
  read endpoint is `GET /fleet/dvirs/history`, which rejects windows longer
  than 30 days, so `fetch_dvirs` walks the requested range in 29-day slices.
- **Safety events page size cap.** `/fleet/safety-events` rejects `limit > 200`
  (`400: "Limit must be <= 200"`), so the call passes `limit=200`.
- **Endpoint fallback.** HOS still tries a list of candidate paths and keeps
  the first that returns rows — Samsara has moved these around.

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

## The driver cert-nudge — `samsara_cert_nudge.py`

The only write-back module in this connector. Runs as the final step of
`samsara_refresh.yml` and posts a Samsara Driver App message to each
driver who has uncertified daily logs in the last 7 days, mirroring
the dashboard's **Missing Certifications** tab. The intent is that
drivers see the nudge in the same app where they take the action
(My Day → certify).

How it works:

1. **Fetches** `/fleet/hos/daily-logs?startDate=…&endDate=…` for the last
   7 days. Each record carries `driver.{id,name}`, `startTime` (day
   boundary in the driver's timezone), and `logMetaData.isCertified`.
2. **Groups uncertified rows by driver.** Today's still-open log is
   dropped (drivers certify end-of-shift), and single-token lowercase
   names (e.g. `tempd`) are skipped as placeholder accounts. Real
   single-token uppercase names like `EYEIGH` pass through.
3. **Composes one message per driver** with a title-cased first name
   ("Hi Lonnie", not "Hi LONNIE"), a count of missing days, and the
   earliest–latest date span.
4. **Sends via `POST /v1/fleet/messages`** — payload `{driverIds, text}`
   — handled by `SamsaraClient.send_driver_messages`.
5. **Writes a OneDrive marker** `Samsara/cert-nudge-sent-{YYYY-MM-DD}.txt`
   so the 3x/day Samsara cron only nudges once per Central-time day.

Token scope: **Driver Workflow → Write Messages** must be enabled on the
API token in the Samsara dashboard. Without it, the POST returns
`HTTP 401: Token requires Messages write permissions to call this
endpoint` and the run carries on; the marker is still written.

Env vars:

- `SAMSARA_API_TOKEN`, Azure creds, `ONEDRIVE_USER_UPN` (for the marker)
- `CERT_NUDGE_DRY_RUN=1` — log what would be sent, skip the POST.
  Useful when changing the message wording or filter heuristics.
- `CERT_NUDGE_FORCE=1` — bypass today's marker. Wired to the
  `force_cert_nudge` boolean input on `workflow_dispatch` so a manual
  rerun after the marker exists actually does something.

Tuning:

- **Skip more drivers** — edit `_is_placeholder_name` in
  `samsara_cert_nudge.py`. Current rule: single-token lowercase names.
- **Reword the message** — `_compose_message`. Keep it under ~150
  chars; long messages get truncated in the Driver App preview.
- **Change the lookback window** — the `start = now - 7 days` in
  `main()`. The dashboard's Missing Certifications tab uses 7d too.

## Common tasks

- **Pull a longer history** → set `SAMSARA_DAYS_BACK` (trips) and/or
  `SAMSARA_SAFETY_DAYS_BACK` (safety / DVIR / HOS violations, default 190).
- **A data type is empty** → almost always an API-token scope problem; the log
  line `GET … → HTTP 4xx — skipping (check API token scope)` tells you which.
- **Alerts not arriving** → confirm `Mail.Send` consent and that
  `ALERT_TO_EMAILS` is set as a secret.
- **Cert nudges silently dropped** → check the log for `Token requires
  Messages write permissions` — fix by enabling **Driver Workflow →
  Write Messages** on the API token in Samsara settings.
