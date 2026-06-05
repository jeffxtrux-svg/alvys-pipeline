# XFreight carrier identity (seeded 2026-06-05 from repo)

> Source: extracted from `docs/knowledge-base/architecture.md` (Carrier identity
> section), `src/scorecard_email.py` `build_csa_scorecard_page`, and live tile
> values on today's executive brief.

## Carrier of record

- **Legal name:** X-Trux, Inc.
- **DOT number:** 841776
- **MC number:** 375851
- **Sister company:** X-Linx, Inc. (brokerage — separate operating authority, shared back office)
- **Trade / parent brand:** XFreight (referenced across docs and emails)

## Active fleet size

- **~15 active power units** (fluctuates).
- The brief's page-1 **Active Trucks · MTD** tile is the live source of truth.
- FMCSA's `AvgPowerUnits` field on the CSA scorecard (currently 67 in the snapshot) is **NOT** the active count — it's a historical carrier-of-record snapshot that includes power units no longer in service. Don't use it as a fleet-size proxy.

## Why these numbers are pinned in the repo

- `dot_number` hardcoded fallback in `compute_csa_scorecard` / `build_csa_scorecard_page` (`src/scorecard_email.py`).
- `mc_num = "375851"` literal in the same function for the page-10 Carrier Identity tile.
- If FMCSA reassigns either number, update both `docs/knowledge-base/architecture.md` and the literal in `src/scorecard_email.py`.

## Pages this appears on

- **Page 1** of the daily brief — Active Trucks · MTD tile.
- **Page 10** — CSA Carrier Scorecard, headline + "Carrier Identity" tile (DOT headline, MC sub-pill) + section header + source-line footer.
