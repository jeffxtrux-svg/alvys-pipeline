# Truk-Way per-truck P&L (the "Truk-Way Trucks" tab)

> **In one sentence:** a Google Sheets tab that breaks Truk-Way's owner-operator
> fleet down to one row per truck — settlement revenue, fuel, and the
> contribution (revenue − fuel) each truck earns — computed from the same Alvys
> pull that feeds the rest of the KPI dashboard.

It lives in the **XFreight KPI Dashboard** Google Sheet as the **`Truk-Way
Trucks`** tab, and is built by `build_trukway_per_truck()` in
`src/sheets_main.py` (called from `pull_alvys`, written by the existing tab
loop). It refreshes on the `sheets_refresh.yml` cron with the other tabs.

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
| **Fuel Cost** | sum of the Alvys fuel-card `Total Due` (falls back to `Net Total`), matched per truck on the fuel `Truck` number (case-insensitive) |
| **Rev − Fuel** | Settlement Revenue − Fuel Cost — i.e. contribution after fuel |
| **Rev / Mile**, **Fuel / Mile** | over total (loaded + empty) miles |

`Advances` and `Customer Revenue` ride along as reference columns (advances are a
pay timing item, not added to revenue; customer revenue is the X-Trux-side
number for context). A **TOTAL** row sums the columns and **recomputes** the
per-mile rates from the totals (not an average of the truck rates).

### The known gap (why it's "contribution," not full net profit)

A truck's **fixed costs** — note/lease, insurance, maintenance, permits, ELD —
live in **Truk-Way Leasing's QuickBooks**, and that file is **not classed per
truck**, so those costs can't be split by truck from the data we pull today. To
get a true per-truck *net* profit you'd need either (A) Truk-Way's QB to tag each
truck as a Class/Customer (then pull a P&L-by-class), or (B) to allocate the QB
company-total expenses across the trucks (e.g. by miles). Until then this tab
stops at **revenue − fuel**.

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
  Confirm by checking whether the fuel tab carries those truck numbers.
- **You want a true net profit** → add a QuickBooks per-truck cost source (option
  A or B above) and subtract it from `Rev − Fuel`.
