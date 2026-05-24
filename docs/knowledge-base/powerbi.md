# Power BI consumption

Power BI is the final consumer of everything this pipeline produces. There are
**two ways** Power BI can get Alvys data, and you should know both because the
repo contains code for each.

## Path A (production today): read Excel from OneDrive

```
Alvys/Samsara/QB APIs → Python pipeline → Excel files → OneDrive → Power BI
```

This is what the GitHub Actions workflows do 3×/day. Power BI is pointed at the
OneDrive files (`Alvys Master 2026.xlsx`, `/Samsara/Samsara Master.xlsx`,
`/QuickBooks/QB_*.xlsx`) and refreshes from whatever the latest upload wrote.

- **Pro:** Power BI setup is trivial (connect to a OneDrive file); no API
  credentials live in the report; the schema matches the original hand-built
  master so existing visuals just work.
- **Con:** an extra hop (the Excel file) and the classic OneDrive friction —
  file locks, and the "change the pipeline → wait for upload → refresh" loop.

The Alvys Excel writer goes to real lengths (date text formats, integer
coercion — see [connector-alvys.md](./connector-alvys.md)) specifically so this
path's Power Query "Changed Type" steps keep working unmodified.

## Path B (alternative): Power BI calls the Alvys API directly

```
Alvys API → Power BI (Power Query M) → visuals     (no Excel, no OneDrive)
```

The `powerbi/` folder contains Power Query **M** code that re-implements the
Alvys pull *inside* Power BI, eliminating the Excel intermediate entirely. Setup
is documented in [`powerbi/SETUP.md`](../../powerbi/SETUP.md).

### What's in `powerbi/queries/`

| File | Becomes a query named | Role |
|------|----------------------|------|
| `_SharedHelpers.pq` | `SharedHelpers` | OAuth + paginated fetch — mirrors `src/alvys_client.py` |
| `Loads.pq` | `Loads` | Loads table |
| `Trips.pq` | `Trips` | Trips table |
| `Fuel.pq` | `Fuel` | Fuel table |

`SharedHelpers` reimplements the exact same auth as the Python client
(Auth0-style JSON body with `audience`, `Bearer` token) and a paginator that
handles the same envelope shapes. It relies on three Power BI **parameters** you
create once: `AlvysClientId`, `AlvysClientSecret`, `AlvysStartDate`. M's lazy
evaluation means the token is fetched exactly once per refresh even though every
table query references it.

### Scope of the M code

`SETUP.md` is explicit that this is a **proof of concept**: only the columns
actually used by visuals (~76, with the `Loads` query covering ~28) are mapped;
everything else returns null. Reaching full parity with the Excel schema is
"mechanical work once the foundation is solid" — Phase 2. So **Path A remains the
source of truth for full-fidelity reporting** until the M queries are completed.

### Why keep both?

Path B is the strategic direction (fewer moving parts, no OneDrive locks), but
it only covers Alvys and only partially. Until it reaches column parity, the
production reports run on Path A. Treat the M code as an in-progress migration,
not a finished replacement.

## Refresh scheduling in Power BI Service (Path B)

When publishing the API-direct report: set the dataset's data-source
credentials to **Anonymous** (we pass a bearer token in code, not Microsoft
auth), skip the test-connection if it complains, and configure scheduled refresh
3×/day to match the old cadence. No on-prem gateway is needed — the Alvys API is
a public cloud endpoint. Full steps and troubleshooting are in `powerbi/SETUP.md`.
