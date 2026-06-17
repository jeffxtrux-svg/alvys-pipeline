---
title: Playbook — Prior Day Logs (Uncertified)
type: playbook
tags: [playbook, safety, compliance, hos, eld, logs, certification, driver, accountability]
status: active
owner: "Audra Newman (Safety & AP)"
last_revised: "2026-06-17"
trigger: "Brief's Teams card shows a Prior Day Logs item for a driver — driver has not certified their ELD log for the prior day within the required 24-hour window"
related: ["[[Progressive Discipline Policy]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Playbook — HOS Violation]]", "[[Driver Roster]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-progressive-discipline-policy.md", "raw/xfreight-safety-program.md"]
---

# Playbook — Prior Day Logs (Uncertified)

## 1. When to Run

Run this playbook when the Teams morning card or the daily email (page 3 — Safety & Compliance Detail) shows a Prior Day Logs flag for a driver. This means Samsara shows the driver has one or more prior-day Electronic Logging Device (ELD) logs that have not been certified by the driver within the required 24-hour window.

Certification is the driver's electronic signature on their daily HOS log — it confirms that the log accurately reflects their duty status for that day. It is a federal regulatory requirement, not a system configuration option.

## 2. What This Means

49 CFR Part 395.8 requires drivers to sign their ELD record for each 24-hour period. The driver must review and certify the prior day's log within 24 hours of the end of that duty period. Electronic logging systems (Samsara's ELD) generate an uncertified-log flag when this window lapses.

FMCSA consequence: Uncertified logs land on the **HOS Compliance BASIC** (intervention threshold: 80th percentile). At a roadside inspection, an inspector who finds uncertified logs can cite the driver for failure to maintain required records of duty status. The underlying HOS data in the log may also be questioned without the driver's certification, which can create compounding citations. Uncertified-log citations stay on X-Trux's FMCSA MCMIS record (DOT #841776) for **24 months**.

Unlike a missing DVIR (which cannot be retroactively submitted), an uncertified log can in some cases be retroactively certified — but the window for doing so is limited and the process may require dispatcher or motor carrier intervention. The fix is for the driver to certify promptly going forward.

## 3. Decision Tree

Uncertified prior-day logs are a driver behavior (administrative compliance) failure, so the standard 4-tier warning ladder applies.

| Occurrence in 30d | Signal in Teams card | Action required | Who acts |
|---|---|---|---|
| 1st | No badge / "1st" | Coach | Audra |
| 2nd | ⚠️ 2nd in 30d | Verbal warning | Audra |
| 3rd | 🔴 3rd in 30d | Written warning | Audra → Jeff drafts |
| 4th+ | 🚨 #N in 30d | Escalate to JB immediately | Audra → JB |

## 4. Action Scripts

**1st — Coach (Level 1):**

> "I'm following up on the uncertified ELD log(s) from [date(s)]. Under 49 CFR Part 395.8, you're required to certify your prior-day log within 24 hours — that's your electronic signature confirming the log is accurate. If an inspector pulls you over and your logs are uncertified, they can cite you for a record-keeping violation, and it affects our HOS Compliance score with FMCSA. Going forward, please certify your log at the end of each day before you shut down — it takes about 30 seconds in the Samsara app. Let me know if there's a technical issue making it hard to do."

**2nd — Verbal Warning (Level 2):**

> "This is the second time in 30 days that you've had uncertified prior-day logs. Per our progressive discipline policy, this is a verbal warning — I'm documenting this in your file now. A third occurrence within 30 days requires a written warning. Certifying your daily log is a federal requirement under 49 CFR Part 395.8. It needs to happen every single day. What's getting in the way?"

**3rd — Written Warning (Level 3):**

> Jeff drafts the letter. Subject line: "[Driver first name]". Cite 49 CFR Part 395.8, the specific dates of the uncertified logs, the prior coaching/verbal warning dates, and the consequence of continued non-compliance. Audra files original in Sharefile → incident file → by year → by driver. Jeff and JB retain working copies.

**4th+ — Escalate:**

Contact JB Sweere directly. JB determines next step.

## 5. Documentation

Record for every level:

- Date(s) the log was uncertified (from Samsara).
- Driver name, truck number.
- Citation: 49 CFR Part 395.8 (driver's record of duty status, certification requirement).
- Expected behavior change (e.g., "certify prior-day log in Samsara before end of each duty day, no exceptions").
- Review date: 30 days.
- Driver signature (Level 2+) or "driver declined to sign, [date]".
- Filed: Sharefile → incident file → [year] → [driver name].
- CC Jeff and JB on Level 3+.

## 6. Decision Points

- **If the driver claims they certified the log but Samsara still shows it uncertified:** Pull the Samsara ELD audit trail. If it's a system error, document the investigation and do not issue discipline. Contact Samsara support to resolve the technical issue.
- **If the driver is consistently late certifying (e.g., 48h instead of 24h) but does eventually certify:** The late certification is still a compliance gap. A pattern of late certifications, even if eventually completed, is citable at roadside if inspected during the uncertified window. Address the behavior, not just the eventual completion.
- **If the log contains HOS data that, once reviewed, shows an actual HOS violation:** The uncertified-log playbook and the [[Playbook — HOS Violation]] both apply. Run both.
- **If the pattern is clustered on weekends or days after long hauls:** This may indicate the driver is shutting down in a location without connectivity. Explore whether offline certification or a scheduled certification reminder in Samsara can help. Address the system/workflow issue alongside the behavioral coaching.
- **If the HOS Compliance BASIC is approaching 80th percentile:** Accelerate discipline. Flag to JB. Issue a fleet-wide certification reminder memo from Audra.

## 7. Escalation

- **JB Sweere:** 4th+ occurrence; HOS Compliance BASIC approaching 80th percentile; pattern of uncertified logs across multiple drivers (fleet-level process failure).
- **Jeff Hannahs:** Level 3 written warning draft; CC on Level 3+.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** If a roadside citation for uncertified logs is received, or if a pattern creates insurance exposure.

## 8. Connections

- [[Playbook — HOS Violation]] — closely related: uncertified logs sometimes reveal underlying HOS violations once the data is reviewed. Run both playbooks if an HOS issue is discovered during the log review.
- [[Progressive Discipline Policy]] — 5-level framework; administrative compliance failures follow the same ladder as driving behavior failures.
- [[Safety Program]] — Samsara HOS compliance tracking, page-3 detail.
- [[FMCSA CSA Scorecard]] — HOS Compliance BASIC (80th percentile threshold); uncertified-log citations land here alongside driving-hour violations.
- [[Driver Roster]] — active drivers; check OO vs. Truk-Way track.
- [[Key People]] — Audra Newman (owner), Jeff Hannahs (drafts letters), JB Sweere (Level 4+).

## 9. Recent Runs *(append-only)*

No runs logged yet.
