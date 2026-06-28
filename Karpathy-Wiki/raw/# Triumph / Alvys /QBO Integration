# Triumph / Alvys / QBO Integration

**Status:** In progress — Alvys owns the build  
**Last updated:** 2026-06-27

## Architecture
Triumph → Alvys (two-way sync) → QuickBooks Online

## Background
XFreight went live with Triumph Business Capital for carrier settlements
week of 6/23/26. Asset side (X-Trux) flows correctly. Brokerage side
(X-Linx) broke at go-live — Alvys was not passing carrier payables to
Triumph alongside AR invoices. Triumph requires both simultaneously.

No two-way data flow existed at go-live. 144 invoices from the initial
buyout were unrecorded in both Alvys and QBO.

## Meeting: 6/26/26 — Jeff + Alvys Integration Team
- Alvys acknowledged the gap; integration team owns the fix
- Alvys CS notified; not pursuing in parallel
- Alvys to sync 144 outstanding invoices to QBO week of 6/30/26
- QBO third-party accounting setup target: week of 6/30 or following week
- Triumph Audit feature to be turned off for XFreight account
- Andreas (Alvys head engineer) to contact Jeff re: sandbox access Monday 6/30

## Decision
Alvys owns this integration entirely. No custom build required from XFreight.
Once complete: Triumph → Alvys (two-way) → QBO.
