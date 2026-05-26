# XFreight Report API — Setup Guide

Connect the full 29-page XFreight Report to live Alvys data (no Excel file needed).

## What you're building

```
Alvys API  →  Power Query (M)  →  Loads / Trips / Fuel tables
                                    ↓
                         29-page Power BI Report
                         (all KPIs, charts, gauges, driver pages, fuel)
```

The finished file is **`XFreight Report API.pbix`** — already built and waiting
in OneDrive → XFreight - Claude Working Files → 02 - Power BI.

---

## Prerequisites

- **Power BI Desktop** (Windows) — free from Microsoft Store
- Your Alvys **Client ID** and **Client Secret**
  (Alvys → Settings → API/Integrations)
- OneDrive synced so you can open the .pbix locally

---

## Step 1 — Open the pre-built file

Open `XFreight Report API.pbix` in Power BI Desktop.

You'll see all 29 pages but the visuals will show **"Data source error"** or
**"Can't load data"** — that's expected. The visual layout is there; we just
need to wire up the data.

---

## Step 2 — Create Alvys credential parameters

**Home → Transform data → Manage Parameters → New Parameter** (repeat 3×):

| Name               | Type | Current value              |
|--------------------|------|----------------------------|
| `AlvysClientId`    | Text | (paste your Client ID)     |
| `AlvysClientSecret`| Text | (paste your Client Secret) |
| `AlvysStartDate`   | Text | `2024-01-01`               |

> Tip: Set AlvysStartDate to the oldest data you want. Farther back = longer
> first refresh. `2024-01-01` is a good starting point.

---

## Step 3 — Paste the Power Query M queries

Still in Power Query Editor (**Home → Transform data**):

### Order matters — paste in this sequence:

#### 3a. SharedHelpers
1. **Home → New Source → Blank Query**
2. **Advanced Editor** → replace everything with contents of `queries/_SharedHelpers.pq`
3. Rename query to **`SharedHelpers`**

#### 3b. Drivers (lookup)
1. New Blank Query → Advanced Editor → paste `queries/Drivers.pq`
2. Rename to **`Drivers`**

#### 3c. Trucks (lookup)
1. New Blank Query → Advanced Editor → paste `queries/Trucks.pq`
2. Rename to **`Trucks`**

#### 3d. Users (lookup)
1. New Blank Query → Advanced Editor → paste `queries/Users.pq`
2. Rename to **`Users`**

#### 3e. Trips
1. New Blank Query → Advanced Editor → paste `queries/Trips.pq`
2. Rename to **`Trips`**

#### 3f. Loads
1. New Blank Query → Advanced Editor → paste `queries/Loads.pq`
2. Rename to **`Loads`**

#### 3g. Fuel
1. New Blank Query → Advanced Editor → paste `queries/Fuel.pq`
2. Rename to **`Fuel`**

#### 3h. Delete the old placeholder queries
If Power BI brought over any old queries from the original PBIX, right-click
and delete them. Keep only the 7 new ones above.

---

## Step 4 — Close & Apply

**Home → Close & Apply** — Power BI will run all queries.

First refresh takes **5–15 minutes** depending on data volume.
You'll see a progress spinner. Let it finish.

---

## Step 5 — Create goal/parameter tables

These power the KPI gauge visuals on the XFreight and Page 2 pages.

**Modeling → New Parameter (What-If)** — create 8 parameters:

| Table Name           | Min  | Max       | Step     | Default  |
|----------------------|------|-----------|----------|----------|
| Goal Revenue Linx    | 0    | 5,000,000 | 50,000   | 600,000  |
| Goal Margin % Linx   | 0    | 1         | 0.01     | 0.18     |
| Goal Revenue Trux    | 0    | 2,000,000 | 25,000   | 350,000  |
| Goal Margin % Trux   | 0    | 1         | 0.01     | 0.25     |
| Empty Mileage Goal % | 0    | 1         | 0.01     | 0.15     |
| Margin %             | 0    | 1         | 0.005    | 0.20     |
| Days in Month        | 1    | 31        | 1        | 21       |
| Days Worked          | 0    | 31        | 1        | 1        |

> Power BI auto-creates a measure (e.g. "Goal Revenue Linx Value") for each
> parameter — you can ignore those, but **do not delete the tables**.

---

## Step 6 — Create the WeekTable

For the **Report Delivery Date** page, you need a date dimension table.

**Modeling → New Table**, paste:

```dax
WeekTable =
ADDCOLUMNS(
    CALENDAR(DATE(2023,1,1), TODAY()),
    "WeekLabel",
        "WE " & FORMAT(
            [Date] + (7 - WEEKDAY([Date], 2)),
            "M/D"
        ),
    "WeekEnd",
        [Date] + (7 - WEEKDAY([Date], 2))
)
```

Then create a relationship:
**Modeling → Manage relationships → New**
- `WeekTable[WeekEnd]` → `Loads[Scheduled Delivery]`  (Many-to-one, Single direction)

---

## Step 7 — Add DAX Measures

Open `queries/DAX_Measures.dax` — it contains all the measures for KPIs,
projections, delivery-date page, and fuel.

**Modeling → New Measure** — paste each measure block individually.

> Tip: Create a blank calculation table to hold all measures cleanly:
> `Modeling → New Table → _Measures = {1}` then hide the `Value` column.
> Put all your new measures in that table using the measure's table dropdown.

---

## Step 8 — Verify relationships

**Modeling → Manage relationships** — confirm:

| From                    | To                       | Cardinality |
|-------------------------|--------------------------|-------------|
| Trips[Load #]           | Loads[Load #]            | Many → One  |
| WeekTable[WeekEnd]      | Loads[Scheduled Delivery]| Many → One  |

Power BI may auto-detect these. If not, create them manually.

---

## Step 9 — Save & Publish

1. **File → Save As** → `XFreight Report API.pbix` (confirm overwrite or new name)
2. **Home → Publish** → select your workspace
3. In Power BI Service → your dataset → **Settings → Scheduled refresh**
   - Turn on refresh, set 3× daily (matching the old Excel pipeline cadence)
   - Authentication: **Anonymous** (token is fetched at query time)

---

## Troubleshooting

### "Expression.Error: The name 'SharedHelpers' wasn't recognized"
Paste SharedHelpers *first*, before any other query.

### "Expression.Error: The name 'Trips' wasn't recognized" (in Loads.pq)
Paste Trips *before* Loads. The Loads query joins to Trips.

### Drivers/Trucks query returns empty
Check that your API credentials are correct and that the `/drivers` and
`/trucks` endpoints are accessible with your subscription.

### Gauge visuals show blank
Goal parameter tables need to be created (Step 5). The gauge `Target Value`
is bound to `Loads[X-Linx Rev Goal]` which is a measure reading from those tables.

### Refresh takes too long
Narrow `AlvysStartDate` (e.g. `2025-01-01`). You can always go back further
after confirming things work.

---

## File map

```
powerbi/
├── SETUP.md                         ← This file
└── queries/
    ├── _SharedHelpers.pq            ← OAuth + paginated fetch
    ├── Drivers.pq                   ← Id → name lookup
    ├── Trucks.pq                    ← Id → number lookup
    ├── Users.pq                     ← Id → name lookup
    ├── Loads.pq                     ← Loads table (full column set)
    ├── Trips.pq                     ← Trips table (full column set)
    ├── Fuel.pq                      ← Fuel table
    ├── GoalTables.pq                ← Instructions for goal parameters
    └── DAX_Measures.dax             ← All KPI measures (copy-paste)
```
