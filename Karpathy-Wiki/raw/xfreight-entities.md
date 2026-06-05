# XFreight entity map (seeded 2026-06-05 from repo)

> Source: `CLAUDE.md` ("What this repo is" + connector docs), `docs/knowledge-base/connector-quickbooks.md`,
> `src/qb_main.py` `_companies()`, scorecard email entity-split rendering, and
> the `RPM_GOAL_OVERHEAD_COMPANIES` constant in `src/scorecard_email.py`.

## The QuickBooks companies (five separate files)

XFreight's accounting lives in five separate QuickBooks Online company files:

| Company | Role | In live pipeline? |
|---|---|---|
| **X-Trux, Inc.** | Asset trucking — the carrier (DOT #841776, MC #375851). Pays owner-operators by the mile. | Yes |
| **X-Linx, Inc.** | Brokerage — sells loads, pays carriers. Priced per load, not per mile. | Yes |
| **Truk-Way Leasing** | Trailer / asset leasing entity. Has its own per-truck P&L tab in the Sheets dashboard. | Yes |
| **N&J Trailers** | Future / not-yet-live. Realm ID and refresh token slots reserved in env. | No (skipped) |
| **N&J Properties** | Future / not-yet-live. Same as above. | No (skipped) |

The three live companies' realm IDs are hardcoded in `src/qb_main.py` `_companies()`. The N&J pair read realm IDs from env and are skipped until their refresh tokens exist.

## How the brief groups them

- **X-Trux + X-Linx = "XFreight" for reporting** — the daily executive brief is scoped to this pair.
- **JW Logistics is excluded throughout** — see `xfreight-jw-logistics-exclusion.md` for the policy.
- **Truk-Way is its own track** — it gets a per-truck P&L tab in the Google Sheets dashboard but is not part of the page-1 entity table on the brief.

## The X-Trux / X-Linx pairing

- **Same back office.** Wages, rent, insurance, depreciation, software — one set of overhead serves both.
- **The rate-per-mile cost-out absorbs the entire combined overhead onto X-Trux miles** (see `xfreight-rate-per-mile-goal.md`). `RPM_GOAL_OVERHEAD_COMPANIES = ("X-Trux Inc", "X-Linx Inc")` and `RPM_GOAL_OVERHEAD_ALLOC = 1.0` (default — 100% of pooled overhead lands on X-Trux miles, because brokerage is priced per load and shouldn't carry per-mile overhead).
- **Margins target differently.** X-Linx has a `XLINX_MARGIN_GOAL = 17.5%` net (carrier-pay net). X-Trux's target is expressed via the rate-per-mile operating ratio (default 0.95 = 5% net on fully-loaded cost).

## Where to see each on the brief

- **Page 1** — both entities have their own block in the Overview's entity P&L. Combined totals roll up at the bottom.
- All other pages combine X-Trux + X-Linx unless otherwise noted.
