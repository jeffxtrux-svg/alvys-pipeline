# Truk-Way per-truck P&L (the "Truk-Way Trucks" tab)

> **In one sentence:** a Google Sheets tab that breaks Truk-Way's owner-operator
> fleet down to one row per truck — settlement revenue, fuel, allocated overhead
> and **net profit** each truck earns — computed from the same Alvys + QuickBooks
> pulls that feed the rest of the KPI dashboard.

It lives in the **XFreight KPI Dashboard** Google Sheet as the **`Truk-Way
Trucks`** tab, built by `build_trukway_per_truck()` in `src/sheets_main.py` and
written from `main()` **after** the Alvys and QuickBooks phases (so it can fold
Truk-Way's QB expenses into the per-truck net). It refreshes on the
`sheets_refresh.yml` cron with the other tabs.

## Why it exists

**Truk-Way is an owner-operator that runs ~10 trucks under X-Trux.** In Alvys it
is modelled as a **Fleet** — `Fleet.Name = "Truk-Way Leasing LLC"`, with
`Fleet.InvoiceNumberPrefix = "T"` (that "T" prefix is the same one QuickBooks
invoices carry, which is why `_norm_inv` strips a leading alpha prefix when
reconciling). Because Truk-Way's loads flow through Alvys under X-Trux, every
piece needed to cost a truck is already in the pull; this tab just regroups it.

## What it shows — and the chosen definition of "profit"

This is **Truk-Way's own** per-truck economics, not X-Trux's margin:

| Concept | How it's computed |
|---|---|
| **Settlement Revenue** | what X-Trux pays the truck = `Driver Rate` (loaded+empty mileage pay) **+** `Carrier Detention` + `Carrier Lumper` + `Carrier Other Accessorials` |
| **Fuel Cost** | sum of the Alvys fuel-card `Total Due` (falls back to `Net Total`), matched per truck on the fuel `Truck` number (case-insensitive) — **reference only** |
| **Rev − Fuel** | Settlement Revenue − Fuel Cost — contribution after fuel (reference) |
| **Allocated QB Cost** | Truk-Way Leasing's **all-in QuickBooks Total Expenses** split across the trucks by each truck's share of total miles |
| **Net Profit** | **Settlement Revenue − Allocated QB Cost** — the true bottom line per truck |
| **Rev / Mile**, **Fuel / Mile**, **Net / Mile** | over total (loaded + empty) miles |

### How "true net profit" is computed (and why fuel isn't double-counted)

The QuickBooks **Total Expenses** for Truk-Way Leasing is an *all-in* figure — it
already includes fuel, insurance, the truck note/lease, maintenance, permits,
everything. We pull it from the `QB_ProfitAndLoss` tab
(`trukway_total_expenses()`), then **allocate it across the trucks by mile
share** and subtract it to get Net Profit. Because the allocated QB cost already
covers fuel, the Alvys per-truck **Fuel Cost stays a reference column and is _not_
subtracted again** — subtracting both would double-count fuel. The Alvys fuel
column is still useful as an actuals cross-check (and for `Fuel / Mile`).

If the QB P&L is missing (e.g. the QuickBooks pull failed, or Truk-Way has no
'Total Expenses' line), the tab **degrades gracefully** to contribution only
(`Rev − Fuel`) and the `Allocated QB Cost` / `Net Profit` / `Net / Mile` columns
are simply omitted.

`Advances` and `Customer Revenue` ride along as reference columns (advances are a
pay timing item, not added to revenue; customer revenue is the X-Trux-side
number for context). A **TOTAL** row sums the columns and **recomputes** the
per-mile rates from the totals (not an average of the truck rates); the allocated
cost on the TOTAL row sums back to Truk-Way's full QB Total Expenses.

### Caveats of the mileage allocation

- It's an **even-by-mile** split, so a truck that runs more miles absorbs more
  overhead — fair for variable costs, rough for fixed ones (a $1,200 insurance
  premium is the same whether the truck ran 8k or 12k miles). For exact
  per-truck fixed costs you'd still need Truk-Way's QB **classed per truck**.
- The QB and Alvys windows are aligned (both use `SHEETS_START_DATE → today`), but
  QB revenue ≠ Alvys settlement, so Net here is an *operational* view
  (settlement − allocated cost), not a literal copy of the QB P&L net income.

### Want exact (not allocated) per-truck costs?

This tab implements **option B** — allocate Truk-Way's QB company-total expenses
across the trucks by miles. The more precise **option A** is to have Truk-Way's
QuickBooks tag each truck as a **Class** (or Customer/Job); then a P&L-by-class
gives each truck's *actual* costs and you'd swap the mileage allocation for the
real per-truck numbers. Until the books are classed that way, the mileage split
is the best available estimate.

## Filtering rules (locked by `tests/test_trukway_per_truck.py`)

- Only loads whose **`Load Fleet`** contains `"truk-way"` (case-insensitive).
- **Cancelled** loads are dropped (no settlement).
- Loads with no **`Truck`** assigned are dropped.
- **Fail-soft:** if the loads frame is empty, lacks a `Load Fleet` column, or has
  no Truk-Way rows, the tab is simply skipped (no crash, matching the pipeline's
  fail-soft design).

## When you'd edit this

- **Truk-Way is renamed in Alvys** → update `TRUKWAY_FLEET_MATCH` in
  `src/sheets_main.py`.
- **Fuel doesn't show up per truck** → owner-ops sometimes self-fuel, so their
  fuel never hits an X-Trux card; `Fuel Cost` will read 0 and the log notes it.
  That's fine for Net Profit (the allocated QB cost already includes fuel); the
  Alvys fuel column is just a reference. Confirm by checking whether the fuel tab
  carries those truck numbers.
- **Net Profit columns are missing** → the QuickBooks `ProfitAndLoss` tab had no
  Truk-Way 'Total Expenses' line (or the QB pull failed); the tab falls back to
  contribution-only. Check `trukway_total_expenses()` against the `QB_ProfitAndLoss`
  tab's `Company` / `RowLabel` values.
- **You want exact per-truck costs** → class Truk-Way's QuickBooks by truck
  (option A above) and replace the mileage allocation with the per-class totals.
