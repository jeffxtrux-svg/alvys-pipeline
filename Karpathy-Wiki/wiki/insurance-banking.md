---
title: Insurance and Banking
type: concept
tags: [insurance, banking, finance, legal-entities]
sources: ["raw/xfreight-insurance-and-banking.md", "raw/xfreight-contact-directory.md"]
related: ["[[Acrisure Dispute]]", "[[XFreight Entities]]", "[[Key People]]", "[[Truk-Way Leasing]]", "[[Rate-Per-Mile Goal]]"]
---

# Insurance and Banking

XFreight's insurance program, banking relationships, and entity identifiers. The current insurance broker is Acrisure Midwest Trust; banking is through First Dakota National Bank (Sioux Falls SD). See [[Acrisure Dispute]] for the active billing reconciliation issue.

## Summary

X-Trux and X-Linx carry commercial auto, cargo, GL, and workers' comp insurance through Acrisure (broker) / Great West Casualty (underwriter). A 2026 liability-insurance rate hike was absorbed into the overhead cost-per-mile pin. Banking is through First Dakota National Bank, officer Mike Flint. Both entities were incorporated January 19, 1999 in South Dakota.

## Key Ideas

- Acrisure's underwriter (Great West Casualty) is effectively a **co-decision-maker on driver hiring** — no hire unless Great West approves the driver's MVR/PSP.
- The 2026 rate hike pushed the overhead pin from $0.92 → $0.98/mi. See [[Rate-Per-Mile Goal]].
- X-Linx's Federal Tax ID is 45-0452444. X-Trux's is not yet captured in the source files.
- Both X-Trux and X-Linx share the same Sioux Falls address and incorporated on the same date.

## Current Insurance Program

### Broker: Acrisure Midwest Trust

- **Current broker** (replaced Fischer Rounds / Transportation Ins Svcs-Pierre).
- Invoices flow through QuickBooks as payee `Acrisure Midwest Trust`.
- Payments: ~$2,240/month via bill.com.
- Key contacts: **Jami Hewitt** (jhewitt@acrisure.com) — driver MVR approvals; **Kurt Swanson** (kswanson@acrisure.com) — renewals. See [[Key People]].
- Active billing dispute: see [[Acrisure Dispute]].

### Primary Carriers (2023 ACORD cert — confirm for current year)

| Coverage | Carrier | NAIC | Limit |
|---|---|---|---|
| Auto liability (X-Linx) | **Great West Casualty** | 11371 | $1M occurrence / $2M aggregate |
| Hired/non-owned auto | Great West Casualty | 11371 | $100,000 |
| General liability | Great West Casualty | 11371 | $1M occurrence / $2M aggregate |
| Cargo (contingent) | Great West Casualty | 11371 | $100,000 ($1,000/unit deductible) |
| Workers' comp | **Technology Insurance Company** | 247643208 | Statutory |

> **Note:** These figures are from a 2023 X-Linx ACORD certificate. Current carriers and limits may differ — verify against the active Acrisure reconciliation.

### 2026 Rate Hike

A liability-insurance rate increase in 2026 pushed costs above the prior $0.92/mi overhead pin. The pin was bumped to **$0.98/mi** to absorb the increase, and the separate `RPM_GOAL_INSURANCE_SURCHARGE` constant was zeroed to avoid double-counting. See [[Rate-Per-Mile Goal]] for the full cost-out methodology.

## Historical Broker

**Transportation Ins Svcs-Pierre / Fischer Rounds** (Pierre, SD) — predecessor broker before Acrisure.

- **Kurt Swanson Jr.** — 800-444-8332 / 605-224-5831 / kswanson@fischerrounds.com
- Later followed his book to Acrisure (now reachable at kswanson@acrisure.com).

## Driver Applicant Insurance Workflow

Every new driver must be approved by Acrisure/Great West before XFreight can hire:

1. Audra Newman runs MVR + PSP Report.
2. Audra emails application + MVR + PSP to Jami Hewitt (jhewitt@acrisure.com).
3. Jami runs it against Great West Casualty underwriting guidelines.
4. Approval or decline returned (decline examples: expired CDL, wrong-state MVR).
5. If approved + hired: Audra creates folders in Sharefile + OneDrive.

See [[Safety Program]] for the full applicant workflow.

## Banking

### First Dakota National Bank

- **Location:** 6109 South Old Village Place, Sioux Falls SD 57108-2104
- **Phone:** 605-333-8210
- **Bank Officer:** Mike Flint (mflint@firstdakota.com)
- **Role:** Primary banking for XFreight entities; working with JB Sweere on the [[SBA 504 Financing]] (~$3M project).

## Entity Identifiers

| Entity | DOT # | MC # | Federal Tax ID | Incorporated |
|---|---|---|---|---|
| **X-Trux, Inc.** | 841776 | 375851 | (not captured) | Jan 19, 1999 (SD) |
| **X-Linx, Inc.** | 2224732 | 353490 | **45-0452444** | Jan 19, 1999 (SD) |
| **Truk-Way Leasing, LLC** | — | — | (not captured) | — |

DOT #841776 and MC #375851 are hardcoded in `src/scorecard_email.py` as the FMCSA identifiers for the CSA Scorecard page. If either number changes, update both `docs/knowledge-base/architecture.md` and the literals in `src/scorecard_email.py`.

## Insurance Files in OneDrive

| File | Location |
|---|---|
| Acrisure reconciliation (master) | `03 - Finance/Insurance/X-Trux Ins/Acrisure/X-Trux Acrisure Reconciliation v3 42826.xlsx` |
| Current Acrisure invoice | `Bills Inbox/Invoice33980.pdf` (received 2026-06-01) |
| X-Trux payments register 2025 | `03 - Finance/Insurance/Final Insurancee.xlsx` |
| X-Linx ACORD certificate | `jbsweere_xfreight_net/aalinxpacket.pdf` (2023 vintage) |

## Connections

- [[Acrisure Dispute]] — active billing reconciliation ($43,739 credits in dispute as of June 2026).
- [[XFreight Entities]] — entity legal structure.
- [[Key People]] — Jami Hewitt (Acrisure), Kurt Swanson (Acrisure), Mike Flint (First Dakota).
- [[Safety Program]] — driver applicant approval requires Acrisure/Great West sign-off.
- [[Truk-Way Leasing]] — workers' comp audit (Inv 29033, $11,024) covers Truk-Way payroll.
- [[Rate-Per-Mile Goal]] — 2026 rate hike absorbed into the $0.98/mi overhead pin.
- [[SBA 504 Financing]] — First Dakota / Mike Flint is the banking partner for the capital plan.

## Sources

- `raw/xfreight-insurance-and-banking.md`
- `raw/xfreight-contact-directory.md`
