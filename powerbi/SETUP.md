# Direct-to-Alvys Power BI Setup

This folder contains Power Query M code that lets Power BI call the Alvys API
directly — replacing the Excel intermediate file. Use this when you want to
eliminate the OneDrive lock issues and the iterate-pipeline-then-refresh
cycle.

## Architecture comparison

```
OLD: Alvys API → Python pipeline → Excel (OneDrive) → Power BI → Visuals
NEW: Alvys API → Power BI (Power Query) → Visuals
```

## What you need

- **Power BI Desktop** (Windows)
- Your Alvys **Client ID** and **Client Secret** (same ones in the GitHub
  Actions secrets — find them in Alvys → Settings → API/Integrations)
- 15–30 minutes for first-time setup

## One-time setup in Power BI Desktop

### 1. Open the existing report

Open `XFreight Report Connected.pbix` (or whichever .pbix you want to
convert) in Power BI Desktop.

### 2. Create parameters for credentials

**Home → Transform data → Manage Parameters → New Parameter**:

| Name              | Type   | Suggested values | Current value          |
|-------------------|--------|------------------|------------------------|
| `AlvysClientId`     | Text   | Any value        | (paste your client ID)  |
| `AlvysClientSecret` | Text   | Any value        | (paste your secret)     |
| `AlvysStartDate`    | Text   | Any value        | `2024-01-01`           |

### 3. Paste in the queries

Still in Power Query Editor:

1. **Home → New Source → Blank Query**
2. **Home → Advanced Editor**
3. Replace the entire contents with the code from `queries/_SharedHelpers.pq`
4. Click Done. Rename the query (left panel) to **`SharedHelpers`**
5. Repeat for `Loads.pq` (rename to `Loads`), `Trips.pq` (rename `Trips`),
   `Fuel.pq` (rename `Fuel`)

### 4. Replace the existing data source

Power BI is currently reading these tables from the Excel file. To swap to
the API:

- Right-click the OLD `Loads` query → **Delete**. Confirm.
- The new `Loads` query you pasted in step 3 now drives every visual that
  used to point at the old one. **Same name = same connection point.**
- Repeat for `Trips` and `Fuel`.

### 5. Apply Changes + close Power Query Editor

Power BI will run all the queries. First refresh takes ~5–10 minutes
depending on history depth.

### 6. Save the .pbix and publish

**File → Save As** → give it a new name like `XFreight Report API.pbix`.
Don't overwrite the existing one until you've confirmed visuals work.

## Scheduling refreshes (Power BI Service)

Once you publish to Power BI Service:

1. **Workspace → Datasets → ⋯ → Settings**
2. Under **Data source credentials**, click **Edit credentials**
3. Authentication = **Anonymous** (we're using a bearer token, not Microsoft auth)
4. **Skip test connection** if it complains; the token is fetched at refresh time
5. Under **Scheduled refresh**, turn on and set 3× daily (matching the old
   workflow)

No on-prem gateway needed — Alvys API is a public cloud endpoint.

## File map

```
powerbi/
├── SETUP.md                       # This file
└── queries/
    ├── _SharedHelpers.pq          # OAuth + paginated fetch (all queries use this)
    ├── Loads.pq                   # Loads table
    ├── Trips.pq                   # Trips table
    └── Fuel.pq                    # Fuel table
```

## Current scope

**Phase 1 (proof of concept):** the most important columns (the 76 actually
used by visuals) are mapped. Other columns return null. This is intentional
— prove the architecture works before grinding through every column.

**Phase 2 (full coverage):** add the remaining ~150 columns to exactly match
the existing Excel schema. Mechanical work once the foundation is solid.

## Troubleshooting

**"Failed to refresh: Authentication error"**
- Verify `AlvysClientId` / `AlvysClientSecret` parameter values are correct
- Try regenerating credentials in Alvys → Settings → API/Integrations

**"DataSource.Error: We couldn't authenticate with..."**
- In Power BI Service: Dataset settings → Data source credentials → Edit →
  set Authentication to **Anonymous** (we handle bearer token in code).

**A column shows wrong values**
- Compare with the Python pipeline output (which we know matches the manual
  master). The M code mirrors the same logic; if they diverge, file a bug.

**Refresh is slow on initial run**
- Expected. 2+ years of trips/loads is a lot of paginated API calls. The
  first run is the slowest; incremental refresh can speed up later runs.
