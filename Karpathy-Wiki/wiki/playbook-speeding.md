---
title: Playbook — Speeding
type: playbook
tags: [playbook, safety, compliance, speeding, samsara, speed, driver, accountability, unsafe-driving]
status: active
owner: "Audra Newman (Safety & AP)"
last_revised: "2026-06-17"
trigger: "Brief's Teams card shows a Speeding item for a driver, or page 4 (Fleet Operations) shows a driver above the speed-flag threshold"
related: ["[[Progressive Discipline Policy]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Playbook — Low Safety Score]]", "[[Driver Roster]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-progressive-discipline-policy.md", "raw/xfreight-safety-program.md"]
---

# Playbook — Speeding

## 1. When to Run

Run this playbook when the Teams morning card or the daily email (page 1 Bottom Line, page 4 Fleet Operations speed table) shows a speeding flag for a driver. Samsara computes each driver's time-over-posted-limit as a percentage of total drive time across three windows: 6-month, 3-month, and month-to-date (MTD). The **peak of the three windows** determines the flag and the comment.

Two entry points:
1. **Teams card / Brief flag:** The driver's speed percentage crossed a comment threshold.
2. **Bottom Line escalation:** The driver appeared in the Bottom Line two consecutive weeks, triggering an automatic Level 2 regardless of the percentage.

## 2. What This Means

49 CFR Part 392.6 prohibits commercial drivers from exceeding posted speed limits. Speed violations detected at roadside (citations, moving violations) land on the **CSA Unsafe Driving BASIC** (intervention threshold: 65th percentile — the most sensitive BASIC; lower than all others). Samsara speed data does not itself flow to FMCSA — but the driving behavior it captures is the same behavior that, at roadside, generates citations. A driver with high time-over-limit is the driver most likely to receive a moving citation if inspected.

Speed violations also feed the **CSA Crash Indicator BASIC** (intervention threshold: 65th percentile) because high-speed driving is the leading predictor of crash severity.

CSA violations stay on FMCSA MCMIS (DOT #841776) for **24 months** (inspections/violations) or **60 months** (crashes). Unsafe Driving BASIC at or above 65th percentile invites intervention — compliance reviews, targeted roadside inspections across the fleet.

## 3. Decision Tree

The speeding playbook has a **non-linear entry point**: the severity of the speed flag determines the starting discipline level, not just the 30-day occurrence count. The warning ladder escalates normally from there.

### Speed Flag → Discipline Entry

| Peak % time over posted limit | Samsara comment | Discipline entry point |
|---|---|---|
| < 1.25% | (No flag) | No action required |
| 1.25–1.74% | "Watch this driver" | Coach (informal; document in file) |
| 1.75–1.99% | "Where is the fire?" | Coach (Level 1 conversation) |
| 2.0–2.24% | "Driver needs a conversation" | Level 1 verbal counseling |
| 2.25–2.49% | "This is too fast" | Level 1 verbal counseling |
| 2.5–2.99% | "Need to sit down with this driver" | Level 1; Level 2 if no improvement in 30 days |
| >= 3.0% | "STOP this driver now" | **Level 2 minimum**; Level 3 if prior speed history exists |

### Bottom Line Escalation

| Trigger | Action |
|---|---|
| Driver named in Bottom Line two consecutive weeks | Automatic Level 2 — regardless of peak % trend |
| Driver showing "improving — keep it up" or "falling fast — keep it up" trend | Excluded from Bottom Line list (still visible on page 4 detail) |

**Improvement pauses escalation but does not reset prior documented levels.** A driver who was issued a Level 2 and then improved is still at Level 2 in their file — the next violation resumes from Level 3.

### 30-Day Recurrence Ladder (from any entry point)

| Occurrence in 30d | Signal in Teams card | Action required | Who acts |
|---|---|---|---|
| 1st at threshold | No badge | Coach / Level 1 (per flag above) | Audra |
| 2nd in 30d | ⚠️ 2nd in 30d | Verbal warning | Audra |
| 3rd in 30d | 🔴 3rd in 30d | Written warning | Audra → Jeff drafts |
| 4th+ in 30d | 🚨 #N in 30d | Escalate to JB immediately | Audra → JB |

Note: A "STOP this driver now" flag (>=3%) enters at Level 2 on first occurrence. If they then appear again in 30 days, the next step is Level 3 — not a repeat Level 2. The occurrence ladder increments from wherever the entry landed.

## 4. Action Scripts

**Coach — "Watch this driver" / "Where is the fire?" (1.25–1.99%):**

> "I noticed your speed numbers in Samsara have you at [X%] time over posted limits over the last [period]. That's in the range where I want to flag it before it gets worse. I know these roads can feel slow when you're trying to make your miles, but time over posted limits is a federal violation — 49 CFR Part 392.6 — and if you get pulled over, it affects our CSA score and goes on your record. I'm logging this conversation in your file. Let's see the number come down over the next 30 days."

**Level 1 — "Driver needs a conversation" / "Need to sit down" (2.0–2.99%):**

> "I need to talk to you about your speed. Samsara is showing [X%] time over posted limits — [Samsara comment]. That's beyond a casual observation; it's a behavior we need to change now. Under 49 CFR Part 392.6, you cannot exceed posted speed limits in a commercial vehicle. Per our progressive discipline policy, this is a verbal counseling — I'm documenting it in your driver file. I expect this number to be below [Y%] in 30 days. What's making it hard to stay at or below the speed limit?"

**Level 2 minimum — "STOP this driver now" (>=3%) / Bottom Line two weeks:**

> Jeff drafts the Level 2 written warning. Subject line: "[Driver first name]". Cite 49 CFR Part 392.6, the specific percentage(s), the Samsara comment, and the CSA consequence. State the expected behavior change and monitoring timeline. Audra files original in Sharefile → incident file → by year → by driver. Jeff and JB retain working copies.

> If prior speed history exists (any documented Level 1 for speeding): enter at Level 3 (Strong Written Notice) instead. Management judgment applies.

**3rd in 30d — Written Warning (Level 3, if not already there):**

> Jeff drafts. Cite all prior dates/levels. Include load restrictions if appropriate (no time-critical, high-value, or specialized loads per Level 3 definition in the progressive discipline policy). Audra files; Jeff and JB retain copies.

**4th+ — Escalate:**

Contact JB Sweere directly. JB determines next step (load suspension OO; unpaid suspension Truk-Way; contract action at Level 5).

## 5. Documentation

Record for every level:

- Peak % across the three windows (6-month, 3-month, MTD) at time of flag.
- Samsara comment generated.
- Whether the driver appeared in the Bottom Line.
- Date(s) of prior speed-related documentation in the file.
- Expected behavior change (specific: "peak % below [X%] within 30 days").
- Review date: 30 days from the coaching/warning date.
- Driver signature (Level 2+) or "driver declined to sign, [date]".
- Filed: Sharefile → incident file → [year] → [driver name].
- CC Jeff and JB on Level 3+.

## 6. Decision Points

- **If the driver is "improving — keep it up" or "falling fast — keep it up":** They are excluded from the Bottom Line. Do not invoke Bottom Line two-week automatic Level 2. Still coach — the underlying % may still be above a flag threshold — but don't apply the BL escalation.
- **If the driver disputes the Samsara % as inaccurate:** Speed data comes from GPS against posted limit maps. Common dispute: road with an incorrect posted limit in the map. Review the Samsara clip — if the GPS speed vs. the actual posted limit shows a map error, note the dispute in the file and do not apply discipline on the disputed events. Flag the map issue to Samsara support.
- **If the driver says dispatch is pressuring them for speed:** Dispatch pressure does not excuse a 49 CFR Part 392.6 violation — the driver is legally responsible for their speed. But it is a management process issue. Loop in Dan and JB to review whether load-timing expectations are creating the pressure.
- **If the CSA Unsafe Driving BASIC is approaching 65th percentile:** Accelerate discipline. Any driver with a speed flag skips to a higher level. Flag to JB. Consider a fleet-wide speed memo from Audra.
- **If a driver receives a roadside citation for speeding:** This is a moving violation affecting CSA. Enter at Level 3 minimum regardless of prior occurrence count — same entry point as preventable accidents and major moving violations per the progressive discipline policy.

## 7. Escalation

- **JB Sweere:** 4th+ occurrence; "STOP this driver now" (>=3%) flag; roadside citation for speeding; Unsafe Driving BASIC approaching 65th percentile; Bottom Line driver two consecutive weeks.
- **Jeff Hannahs:** Level 2+ draft letter; CC on Level 2+ (speeding is explicitly named as a Level 2 minimum at >=3%).
- **Dan Heeren:** If dispatch timing is contributing to speed pressure; loop in to align load-timeline expectations.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** Roadside citation for speeding, or if a driver's speed pattern creates insurance exposure. Great West may independently require removal from covered equipment.

## 8. Connections

- [[Playbook — Low Safety Score]] — speeding events are a major driver of Samsara safety scores. A driver on the speeding list is likely also on the low-safety-score list. Apply the higher discipline level.
- [[Progressive Discipline Policy]] — Samsara speed-flag → discipline mapping (Section 4); Bottom Line two-week automatic Level 2; improvement pauses but does not reset levels.
- [[Safety Program]] — speed-over-limit rubric (page 4 detail table + page-1 Bottom Line); trend phrase logic; BL exclusion for improvers.
- [[FMCSA CSA Scorecard]] — Unsafe Driving BASIC (65th percentile — most sensitive BASIC); Crash Indicator BASIC (65th).
- [[Driver Roster]] — active drivers; check OO vs. Truk-Way track for discipline track selection.
- [[Key People]] — Audra Newman (owner), Jeff Hannahs (drafts Level 2+ letters), JB Sweere (Level 4+), Dan Heeren (dispatch alignment), Jami Hewitt (insurance).

## 9. Recent Runs *(append-only)*

No runs logged yet.
