---
title: Daily Operations
type: concept
tags: [operations, schedule, communications, people]
sources: ["raw/xfreight-daily-operations-reports.md", "raw/xfreight-contact-directory.md"]
related: ["[[Daily Schedule]]", "[[Daily Scorecard Email]]", "[[Key People]]", "[[Driver Roster]]"]
---

# Daily Operations

How XFreight runs day-to-day: the three recurring email cadences, the operating rhythm from 2:30am CT data pulls through overnight driver runs, escalation patterns, and a full staff phone directory.

## Summary

The daily executive brief (5:00am CT) is the anchor of XFreight's morning management cycle. Two other recurring email streams — weekly fuel reports (Mondays) and a real-time Available Equipment List — complete the operations picture. Four named employees run the office: JB Sweere (President), Jeff Hannahs (VP BD), Audra Newman (Safety/AP), and Dan Heeren (Logistics Manager).

## Key Ideas

- The daily brief surfaces things that would otherwise never reach anyone's inbox (speed escalations, AR aging shifts, equipment overdue inspections) — that's why it's the central daily management tool.
- Weekly fuel spend averages ~$7K (~$28K/month) on the ~15-truck active fleet.
- The Available Equipment List is updated throughout the day and linked from every outbound Jeff email — it's the broker/customer-facing real-time capacity view.
- Dan Heeren's phone line (605-336-31xx) is a different block from the main office (605-543-83xx), likely a separate dispatch line.

## Three Recurring Email Cadences

### 1. Daily Executive Brief

| Attribute | Value |
|---|---|
| **From** | jeff@xfreight.net (automated via GitHub Actions) |
| **Subject** | "Your daily XFreight Executive Brief for {Month Day, Year}" |
| **Time** | 5:00 AM Central (year-round) |
| **To** | jeff@xfreight.net + jb@xfreight.net (added 2026-06-05, PR #93) |
| **Body** | 13-page PDF, Jeff's contact signature, "Available Equipment List" link |

See [[Daily Scorecard Email]] for the full 13-page structure.

### 2. Weekly Fuel Reports

- **From:** jeff@xfreight.net (automated or manual)
- **Subject:** "X-Trux Fuel Reports — Week_YYYYMMDD"
- **Cadence:** Weekly, Mondays

**Recent weekly totals:**

| Week starting | Total Billed | Comdata | Pilot/Flying J |
|---|---|---|---|
| 2026-05-29 | $7,629.69 | $7,240.98 | $388.71 |
| 2026-06-01 | $9,227.22 | $7,051.40 | $2,175.82 |
| 2026-06-04 | $5,612.81 | $5,612.81 | $0 |

Average ~$7K/week ≈ $28K/month across the active fleet.

**Report contents:** Daily Fuel Purchase Summary, Total Billed (all stops), QB Upload - Comdata Fuel, QB Upload - Pilot/Flying J.

### 3. Available Equipment List (Daily)

- Updated throughout the day by dispatch
- URL linked from Jeff's email signature on every outbound message
- Lets brokers and customers see real-time equipment availability
- Tied to dispatch operations + Highway.com / load board integrations

## Other Automated Emails

- **Highway.com broker connection notifications** — when brokers' carrier packets complete (Bridge Logistics, RL Solutions, etc.)
- **SambaSafety CSA Scorecard - Driver List** — manual export from SambaSafety, attached to email (sent by Audra, April/May 2026 cycle)
- **Acrisure MVR approvals** (Jami Hewitt → Audra) — per-applicant reply emails
- **Daily/weekly bill.com invoice notifications** — Acrisure payments etc.

## Daily Operating Rhythm

```
2:30am CT    SambaSafety merge (auto) — lands before scorecard so data is fresh
4:00am CT    Alvys + Samsara + QB pulls (auto)
4:30am CT    Google Sheets KPI dashboard refresh (auto)
5:00am CT    Daily executive brief emailed (auto)
   ↓
~6–8am CT    Jeff + JB read brief, address any escalations
   ↓
Morning      Audra: MVR approvals, applicant processing, safety follow-ups
             Dan:  load planning, equipment list maintenance, broker comms
             Jeff: customer relationships, sales calls
             JB:   strategic decisions, financial reviews
   ↓
Throughout   Available Equipment List updated as loads move
   ↓
Monday AM    X-Trux Fuel Reports emailed (weekly summary)
   ↓
11:00am CT   Alvys + Samsara + QB pulls (midday refresh)
1:00pm CT    Sheets dashboard refresh
   ↓
5:00pm CT    Final pulls + Sheets refresh
   ↓
Overnight    Drivers run loads; safety events flow to Samsara
```

## What Gets Escalated (by Person)

| Topic | Who |
|---|---|
| DOT inspection violations | Jeff drafts written warning → Audra files |
| Customer payment delays / POD | Jeff or accounts chase |
| MVR / applicant review | Audra ↔ Acrisure (Jami Hewitt) |
| Acrisure billing disputes | Jeff + JB jointly |
| Customer rate / contract questions | Jeff (customer-facing) or JB (strategic) |
| Capital / banking | JB primary, Jeff CC |
| Equipment repair estimates | JB receives (e.g. CSM Truck) |
| Customer rules updates | Dan shares to dispatch |

## What's Only in the Brief (Not in Email)

The brief surfaces items that would otherwise not reach anyone's inbox:

- Per-driver speed-over-limit % with STOP / sit-down escalations
- Fleet idle ranking
- AR aging shifts
- QB-vs-Alvys reconciliation variances
- Equipment overdue inspections (120-day company policy)

## Phone Directory

| Name / Line | Number | Notes |
|---|---|---|
| Office (main) | 605-543-8383 | X-Trux / X-Linx office |
| Toll-free | 800-898-6061 | Customer-facing |
| Toll-free (alt) | 800-468-9701 | Older JB signature |
| JB Sweere (ext) | 605-543-8383 x8357 | |
| JB fax | 605-543-8387 | |
| Jeff Hannahs (direct) | 605-543-8358 | |
| Jeff mobile | 605-431-6959 | |
| Jeff fax | 605-543-8386 | |
| Audra Newman (direct) | 605-543-8352 | |
| Audra fax | 605-543-8382 | |
| **Dan Heeren (direct)** | 605-336-3188 | Different number block — likely separate dispatch line |
| Dan fax | 605-336-3181 | |
| Office fax | 605-543-8366 | |

## Personnel Summary

Four confirmed named XFreight employees as of mid-2026:

| Person | Role | Email |
|---|---|---|
| **JB Sweere** | President | jb@xfreight.net |
| **Jeff Hannahs** | VP Business Development | jeff@xfreight.net |
| **Audra Newman** | Safety & AP | audra@xfreight.net |
| **Dan Heeren** | Logistics Manager | dan@xfreight.net |

Owner-operators are contractors, not employees. There are likely additional dispatchers and office admin not yet surfaced in source documents.

## Connections

- [[Daily Schedule]] — the automation cron schedule (pull cadences, DST pattern).
- [[Daily Scorecard Email]] — the 13-page brief at 5:00am CT.
- [[Key People]] — full contact details and role descriptions for each person.
- [[Driver Roster]] — driver pay timing and settlement week cycle.
- [[Technology Stack]] — Comdata fuel card, bill.com, Highway.com integrations.

## Sources

- `raw/xfreight-daily-operations-reports.md`
- `raw/xfreight-contact-directory.md`
