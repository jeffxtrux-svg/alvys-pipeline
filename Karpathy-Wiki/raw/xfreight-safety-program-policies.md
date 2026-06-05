# XFreight safety program — policies + driver oversight (seeded 2026-06-05 from Outlook)

> Source: Audra Newman ↔ Jeff Hannahs ↔ JB Sweere email threads, April 2026
> + Jami Hewitt (Acrisure) MVR approval workflow.

> **Note:** This is the **business policy** side of safety. The code-level
> safety rubric (speed-over-limit thresholds, coaching policy, page-4 detail
> table logic) is documented at `xfreight-safety-program.md`.

## X-Trux Driver Safety Manual

- **Document:** `X-Trux Driver Safety Manual` — Safety rules for Drivers and Owner-Operators
- **Maintained by:** Audra Newman
- **Last major revision:** **January 1, 2022**
- **Distribution:** Sent to drivers at hire; updates sent periodically. Jeff and JB have working copies for reference.
- **Email subject pattern:** "X-Trux Safety Policy" / "Safety Program" — Audra sends to JB and Jeff

The safety manual covers:
- Hours of Service compliance
- Pre-trip / post-trip inspections (with the X-Trux 120-day company policy on top of federal DOT annual)
- DOT roadside inspection protocol for drivers
- Accident reporting + investigation
- Drug and alcohol testing program
- Driver qualifications (CDL / DOT medical card / MVR)
- Owner-operator obligations
- Disciplinary process (warning letters → suspension → termination)

## File storage

Per Audra's email "Information requested" (Apr 23, 2026), the safety record system uses **Sharefile**:

```
Sharefile – Audra – safety
└── new driver truck printouts

Sharefile – incident file – 2014–current
├── By year
└── By driver

Accidents – last 3 yrs by driver
└── (subset of incident file)
```

So XFreight maintains accident/incident records going back to **2014** organized by year and by driver. The pipeline does not currently read these — they're for internal reference, audit response, and DOT inspection support.

## Driver applicant approval workflow

Every prospective driver runs through this chain:

```
1. Applicant fills out X-Trux application
       │
       ▼
2. Audra runs MVR + PSP Report (FMCSA Pre-Employment Screening Program)
       │
       ▼
3. Audra emails application + MVR + PSP to Jami Hewitt at Acrisure (jhewitt@acrisure.com)
       │
       ▼
4. Jami runs against Great West Casualty's underwriting guidelines
       │
       ▼
5a. Approval → "applicant meets Great West's guidelines, please let me know if hired"
5b. Decline → flag specific issues (e.g. expired MVR in SD, need to pull NE CDL instead)
       │
       ▼
6. If approved + hired, Audra creates driver folder in Sharefile + OneDrive
       │
       ▼
7. Driver onboarded; truck assigned; appears in dispatch + Alvys
```

### Recent applicant examples (from Outlook)

- **Paul Stimac** — Approved by Great West Dec 29, 2025 (Jami Hewitt to Audra)
- **John F Nuttall** — Applied Jan 13, 2026. Initial MVR was expired SD CDL; Acrisure pulled NE CDL instead. Process still in motion as of seed date.

## Disciplinary process

Discipline is **documented in writing**. Example:

**Brad — Written Warning, March 12, 2026** (subject: "Brad")
- DOT Inspection Violation: **Chafed Brake Hoses**
- Cited in Wisconsin by a DOT officer
- Likely 49 CFR Part 393 violation (brake hose/tubing condition)
- Maps to driver "BradM" / truck 43195 in the roster (`xfreight-drivers-roster.md`)

Pattern: Jeff drafts the warning letter, Audra files it, copy goes in the driver's incident file.

## Safety insurance + driver fitness

Tightly coupled with Acrisure's underwriter requirements:
- Pre-hire MVR + PSP screening through Acrisure
- Insurance carrier (Great West) sets the bar for who can drive a Great-West-insured X-Trux truck
- Drivers not meeting Great West guidelines = can't drive = can't be hired
- Effectively makes Acrisure / Great West a co-decision-maker on hiring

## What ties back to the pipeline

The safety program shows up in the brief:

- **Page 2** (Driver Compliance) — SambaSafety MVR-based risk index, license expirations, DOT medical-card expirations
- **Page 3** (Safety & Compliance Detail) — Samsara safety events (last 7d, last 24h), HOS violations, DVIR defects
- **Page 4** (Per-Driver Safety Scores) — Speed-over-limit %, "STOP this driver now" / "Need to sit down" comments
- **Page 5-6** (Equipment Compliance) — tractor + trailer inspections with 120-day company policy + 365-day federal rule
- **Page 10** (CSA Carrier Scorecard) — FMCSA BASIC percentile ranks

The safety manual + Audra's manual files are the **underlying procedural foundation**. The brief surfaces the **measurable outputs** of that program.

## Audra's daily safety responsibilities

From the email pattern:
- Process new driver applications + MVR pulls
- File DOT inspection results, accident reports, incident reports
- Maintain trucking insurance compliance (work with Acrisure on renewals)
- Track CDL / DOT medical card expirations (manually before — now also automated via the brief)
- Handle workers' comp claims
- Send safety policy updates to drivers and management
