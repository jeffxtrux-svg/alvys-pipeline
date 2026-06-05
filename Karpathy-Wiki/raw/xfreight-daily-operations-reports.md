# XFreight daily operations + reporting cadence (seeded 2026-06-05 from Outlook)

> Source: Daily exec brief emails, weekly fuel reports, Available Equipment
> List references.

## Three recurring email cadences

XFreight runs three distinct **scheduled / recurring email** processes that emit to mailboxes:

### 1. Daily executive brief (the one this whole repo is about)

- **From:** jeff@xfreight.net (automated send via the GitHub Actions pipeline)
- **Subject:** "Your daily XFreight Executive Brief for {Month Day, Year}"
- **Time:** 5:00 AM Central (year-round, dual-cron + CT-hour-gate pattern)
- **To:** jeff@xfreight.net (+ jb@xfreight.net as of 2026-06-05 PR #93)
- **Body:** 13-page PDF, Jeff's contact signature, "Available Equipment List" link
- **Tied to:** This entire repo's pipeline

### 2. Weekly fuel reports

- **From:** jeff@xfreight.net (automated; manual or script — TBD)
- **Subject:** "X-Trux Fuel Reports — Week_YYYYMMDD"
- **Cadence:** Weekly (Mondays per the dates observed)
- **Content:**
  - Daily Fuel Purchase Summary
  - Total Billed (all stops)
  - QB Upload - Com Data Fuel
  - QB Upload - Pilot/Flying J
  - Reports attached

#### Recent week totals (signal on current fuel spend)

| Week starting | Total Billed | Comdata | Pilot/Flying J |
|---|---|---|---|
| 2026-05-29 | $7,629.69 | $7,240.98 | $388.71 |
| 2026-06-01 | $9,227.22 | $7,051.40 | $2,175.82 |
| 2026-06-04 | $5,612.81 | $5,612.81 | $0 |

Average ~$7K/week = ~$28K/month fuel cost on the active fleet (~15 trucks).

### 3. Available Equipment List (daily)

- **Updated throughout the day** (per the link in Jeff's email signature)
- **URL pattern:** Linked from each outbound email signature
- **Purpose:** Lets brokers and customers see real-time equipment availability
- **Tied to:** dispatch operations + Highway.com / load board integrations

## Other observed automated emails

- **Highway.com broker connection notifications** — when brokers' carrier packets complete (e.g. Bridge Logistics, RL Solutions confirmations)
- **SambaSafety CSA Scorecard - Driver List** emails sent by Audra (Apr/May 2026) — manual export from SambaSafety, attached to email
- **Acrisure MVR approvals** (Jami Hewitt) — per-applicant reply emails
- **Daily / weekly bill.com invoice notifications** (Acrisure payments etc.)

## Operational personnel (newly surfaced)

### Dan Heeren — Logistics Manager
- **Email:** dan@xfreight.net
- **Phone:** P 605-336-3188, F 605-336-3181 *(note: different phone block from Jeff/JB's 543-83xx range — suggests Dan works from a different desk or different line)*
- **Role:** Day-to-day load planning, customer accessorial rules management, dispatch coordination
- **Observed:** Sent "Berry" email May 12, 2026 with Berry Global Truckload Rules and Accessorial Charges document

This brings the named XFreight team to **four** confirmed:
- JB Sweere (President)
- Jeff Hannahs (VP BD)
- Audra Newman (Safety + AP)
- **Dan Heeren (Logistics Manager)** — new this batch

There are likely additional dispatchers, drivers, and possibly office admin not yet surfaced in the documents I've read.

## Phone number map (updated)

Three distinct number ranges in use at XFreight:

| Range | Owner | Notes |
|---|---|---|
| **605-543-83xx** | Office (Jeff, JB, Audra) | Main XFreight office numbers |
| **605-336-31xx** | Dan Heeren | Logistics line (possibly a separate office or older XFreight number kept for dispatch) |
| **800-898-6061** | Toll-free | Customer-facing toll-free |
| **800-468-9701** | Toll-free (alt — JB used this in an older email signature) | Earlier toll-free for invoices/operations |
| **605-543-8358** | Jeff direct | Per his email signature |
| **605-431-6959** | Jeff mobile | Per his email signature |
| **605-543-8352** | Audra direct | Per her email signature |
| **605-543-8383 x8357** | JB extension | Per his email signature |
| **605-543-8366** | Office fax (X-Linx packet) | |
| **605-543-8386** | Jeff fax | |
| **605-543-8387** | JB fax | |
| **605-543-8382** | Audra fax | |
| **605-336-3181** | Dan fax | |

## Daily operating rhythm (reconstructed)

```
2:30am CT    SambaSafety merge (auto)
4:00am CT    Alvys + Samsara + QB pulls (auto)
4:30am CT    Sheets dashboard refresh (auto)
5:00am CT    Daily executive brief emailed (auto)
   ↓
~6-8am CT    Jeff + JB read brief, address any escalations
   ↓
Morning      Audra: MVR approvals, applicant processing, safety follow-ups
             Dan: load planning, equipment list maintenance, broker comms
             Jeff: customer relationship work, sales calls
             JB: strategic decisions, financial reviews
   ↓
Throughout   Available Equipment List updated as loads move
   ↓
Monday AM    X-Trux Fuel Reports emailed (weekly summary)
   ↓
11:00am CT   Alvys + Samsara + QB pulls (midday — keeps OneDrive fresh)
1:00pm CT    Sheets dashboard refresh
   ↓
5:00pm CT    Final pulls + Sheets refresh
   ↓
Overnight    Drivers run loads; safety events flow to Samsara
```

## What gets escalated

Based on observed email patterns:

- **DOT inspection violations** → Jeff drafts written warning, Audra files
- **Customer payment delays** → Jeff or accounts chase POD submission
- **MVR / applicant review** → Audra ↔ Acrisure (Jami)
- **Acrisure billing disputes** → Jeff + JB jointly negotiate
- **Customer rate / contract questions** → Jeff (customer-facing) or JB (strategic)
- **Capital / banking** → JB primary, Jeff in CC
- **Equipment repair estimates** → JB receives (CSM Truck example)
- **Berry-style customer rules updates** → Dan shares to dispatch team

## What's NOT in email but is in the brief

The daily executive brief surfaces things that don't have a corresponding email:

- Per-driver speed-over-limit comments
- Fleet idle ranking
- AR aging shifts
- QB-vs-Alvys reconciliation variances
- Equipment overdue inspections (120-day company policy)

These would never get into anyone's inbox without the brief — that's why the brief is the central daily-management tool.
