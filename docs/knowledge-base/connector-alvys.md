# Connector: Alvys (TMS)

The Alvys connector is the oldest and most elaborate, because its output has to
match a pre-existing hand-maintained `Alvys_Master.xlsx` column-for-column.

- **Entry point:** `python -m src.main`
- **Output:** `output/Alvys_Master.xlsx` with three sheets — **Fuel, Loads, Trips**
- **Files:** `main.py`, `alvys_client.py`, `column_mappings.py`, `lookups.py`,
  `transformers.py`, `output_writer.py`

## Authentication

OAuth2 **client-credentials**, Auth0-style (`alvys_client.py`):

- Token URL: `https://auth.alvys.com/oauth/token`
- The body is **JSON** (not form-encoded) and **must include `audience`**:
  `https://api.alvys.com/public/`, plus `client_id`, `client_secret`,
  `grant_type=client_credentials`.
- Token is cached in-memory and reused until 60s before `expires_in`.
- API base: `https://integrations.alvys.com/api/p/v1`
- Every request sends `Authorization: Bearer <token>`.

Credentials come from `ALVYS_CLIENT_ID` / `ALVYS_CLIENT_SECRET`.

## What it fetches

### Core data (the three sheets)

All three use `POST /<resource>/search` with body-based pagination
(`page`, `pageSize=100`, 0.2s sleep between pages). The paginator
(`_paginate_search`) tolerates several response envelope shapes
(`Items`/`items`/`data`/`results`, `Total`/`TotalCount`/…).

| Method | Endpoint | Filter | Sheet |
|--------|----------|--------|-------|
| `fetch_loads` | `/loads/search` | all statuses + `updatedAtRange` | Loads |
| `fetch_trips` | `/trips/search` | all statuses + `updatedAtRange` | Trips |
| `fetch_fuel` | `/fuel/search` | `transactionRange` | Fuel |

The date window starts at `ALVYS_START_DATE` (default: today − 425 days; the
workflow pins it to `2024-01-01`) and ends "now."

### Reference data (for enrichment)

`fetch_drivers / trucks / trailers / users / offices / subsidiaries / carriers /
customers / invoices`. Most try a `GET` first then fall back to `POST /…/search`
(`_fetch_with_fallback`), and try several status-filter shapes because the API
is picky and inconsistent about required fields (e.g. customers require a
capital-S plural `Statuses` field; invoices require one of
`Status`/`PONumbers`/`CustomerId`/…). Optional ones degrade to `[]` on failure.

## How JSON becomes columns (the important part)

Three pieces work together:

### 1. `column_mappings.py` — the declarative schema (874 lines)

`LOADS_COLUMNS`, `TRIPS_COLUMNS`, `FUEL_COLUMNS` are lists of
`(excel_column_name, accessor)` tuples. The accessor is one of:

- a **string** — a dot-notation path through the JSON, e.g.
  `"Stops.first.Address.City"`. Supports `first` / `last` to index into list
  fields. Case-insensitive at every level.
- a **callable** — `function(record) -> value`, for computed or enriched columns
  (lookups, joins, gross-margin math).
- `None` — an intentional placeholder for a column that only exists in the Alvys
  UI / real-time and can't be pulled from the API.

> **This is the file you edit when a column comes back blank.** You don't change
> code logic — you fix the path string or callable for that one column.

### 2. `lookups.py` — turning IDs into names + joining sheets

The Alvys API returns `{Id, Fleet}` stubs for drivers/trucks/carriers, not
names. `build_lookups(client)` runs once at startup and fills in-memory dicts:

```
drivers   Id → "First Last"        carriers              Id → name
trucks    Id → TruckNumber         factoring_by_carrier  Id → factoring co.
trailers  Id → TrailerNumber       customers_by_id       Id → full record
users     Id → "First Last"        truck_fuel_cards      TruckId → {card…}
offices / subsidiaries  Id → name
```

It also builds **cross-sheet join indexes** (`build_join_index`): `loads_by_num`,
`trips_by_num`, `trips_count_by_load` keyed by `LoadNumber`, so a Load row can
pull fields from its Trip and vice-versa. `build_invoice_index` buckets invoices
into customer-vs-carrier by `LoadNumber`. The column-mapping callables
(`_name_from_id`, `_from_trip`, `driver1_rate`, …) read these dicts directly.

Overrides: set `ALVYS_OFFICE_MAPPINGS` to a JSON dict to hard-map office IDs to
names when the API doesn't expose them.

### 3. `transformers.py` — the apply engine

`transform_records(records, column_map)` builds one row dict per record by
resolving every accessor, then returns a DataFrame with columns in mapping
order. It also **unwraps Alvys's nested value blobs**, a recurring API quirk:

```
{"Amount": 2000.0, "Currency": 840}                  → 2000.0
{"Value": 174.11, "UnitOfMeasure": "Gallons"}        → 174.11
{"Distance": {"Value": 1270.0, …}, "Source": …}      → 1270.0
```

`report_blank_columns` logs any column that came out entirely empty — your
signal that a mapping path is wrong.

## Writing the Excel file — `output_writer.py`

`write_master_xlsx` writes sheets in the exact legacy order **Fuel, Loads,
Trips** and reproduces two finicky formatting rules so Power Query's existing
"Changed Type" steps don't error:

- **Dates → `MM-DD-YYYY` text, date-only.** Date-like columns are auto-detected
  by sampling (≥70% of values match an ISO-8601 or human date pattern). ISO
  timestamps are parsed and converted to **America/Chicago** before formatting.
  Time components are stripped uniformly (a time suffix made Power Query throw
  per-row type errors).
- **Business-number columns → integers** where they parse cleanly
  (`Load #`, `Order #`, `Truck`, `Trailer`), matching how the manual file stored
  them; non-numeric values are left as their original string.

## Debug artifacts

A run writes to `output/_debug/`:

- `sample_loads.json`, `sample_trips.json`, `sample_fuel.json` — first raw record
  from each endpoint (inspect to find correct field paths).
- `sample_<reference>.json` — first record of each reference fetch.
- `driver1_rate_types.json` — an inventory of `Driver1.Rates` (legacy) vs
  `Driver1.RatesV2` (policy objects) structures, because driver-pay mapping is
  the trickiest part of the schema.
- `sample_trip_carrier.json` — the `trip.Carrier` shape (brokered X-LINX trips
  carry `Carrier.Rate.Amount`, used for "Carrier Rate").

## Drivers sheet — CDL + DOT medical card tracking

In addition to Fuel / Loads / Trips, `write_master_xlsx` writes a
**`Drivers`** sheet to `Alvys_Master.xlsx`. The sheet is a compact
projection of the `/drivers` API response — only the fields the
scorecard's driver-compliance page needs:

| Column | Source field | Notes |
|--------|--------------|-------|
| Id | `Id` | Alvys driver UUID |
| Name | `Name` | Full name |
| Type | `Type` | Owner Operator / Company Driver / etc |
| Status | `Status` | Active / Inactive / Terminated |
| LicenseNum | `LicenseNum` | CDL number |
| LicenseState | `LicenseState` | Issuing state |
| **LicenseExpiresAt** | `LicenseExpiresAt` | CDL expiration date |
| **MedicalExpiresAt** | `MedicalExpiresAt` | **DOT medical card / DOT physical** expiration |
| HiredAt | `HiredAt` | |
| TerminatedAt | `TerminatedAt` | Null = active |

`compute_alvys_drivers` in `scorecard_email.py` reads this sheet,
filters out terminated/inactive drivers, and buckets the rest into:

- `license_issues_30` / `medical_issues_30` — pipeline view (any
  expiration inside 30 days).
- `license_critical_14` / `medical_critical_14` — operationally urgent
  (inside 14 days). These get named individually in the BOTTOM LINE.

A 7-day window inside that triggers the `DOT MEDICAL CARD · NAME`
action card (severity `bad`) — an expired CDL or medical card grounds
the truck the same way.

Page 2 of the scorecard renders a "DOT medical card · expirations
within 30d" table from this data, alongside the SambaSafety license /
MVR sections — so page 2 becomes a single-stop driver-compliance view.

## Common tasks

- **A column is blank that shouldn't be** → open `output/_debug/sample_*.json`,
  find the real field path, fix that one entry in `column_mappings.py`, re-run.
- **Pull more/less history** → set `ALVYS_START_DATE` (env or workflow).
- **Rate-limited (HTTP 429)** → bump the `time.sleep(0.2)` in
  `alvys_client._paginate_search`.
- **Medical card or CDL expiration column blank on page 2** → Alvys
  renamed the driver field. Check `sample_drivers.json` for the new
  key and update the candidate list in `compute_alvys_drivers`
  (`_col(...)` calls near the top of the function).

See [operations.md](./operations.md) for the full runbook.
