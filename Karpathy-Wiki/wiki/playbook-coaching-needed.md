---
title: Playbook — Coaching Needed / Needs Disposition
type: playbook
tags: [playbook, safety, compliance, coaching, samsara, accountability, unsafe-driving]
status: active
owner: "Audra Newman (Safety & AP)"
last_revised: "2026-06-17"
trigger: "Brief's Teams card shows a 'Coaching Needed' or 'Needs Disposition' item for a driver — driver has 2+ unacknowledged Samsara safety events in the last 30 days, or an open coaching session not yet closed"
related: ["[[Coaching Ack]]", "[[Progressive Discipline Policy]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Driver Roster]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-progressive-discipline-policy.md", "raw/xfreight-safety-program.md"]
---

# Playbook — Coaching Needed / Needs Disposition

## 1. When to Run

Run this playbook when the Teams morning card or the daily email (page 3 — Safety & Compliance Detail, "Coaching Needs Assigned" list) shows a driver in either of two states:

- **Coaching Needed:** Driver has 2 or more unacknowledged Samsara safety events in the last 30 days and no coaching session has been opened or completed.
- **Needs Disposition:** Driver has a coaching session that was opened (assigned) but not yet closed — the session status has not reached coached / dismissed / recognized.

Drivers stay on the list until all events in the 30-day window are acknowledged, then for 3 more days as a closeout indicator. Single events (below the 2-event threshold) appear as "Monitor" and roll off naturally after 7 days — they do not trigger this playbook.

## 2. What This Means

Samsara records safety events — harsh braking, hard cornering, following-too-close, distracted driving, speeding, lane departure — and flags them for review. The coaching program requires a session to be opened for each flagged driver and completed (status = coached, dismissed, or recognized) before the event is considered acknowledged.

**Critical technical note:** Ack state is derived from the **SafetyEvents sheet** (`coachingStatus` field: coached / dismissed / recognized = acked). It is NOT derived from the CoachingSessions sheet. The `/coaching/sessions` Samsara endpoint 404s for XFreight's account; that sheet is an empty placeholder. Any investigation of coaching status must use the SafetyEvents data.

No 49 CFR regulation directly mandates Samsara coaching. However, the underlying safety events (speeding, following distance, harsh braking, distracted driving) feed the **CSA Unsafe Driving BASIC** (intervention threshold: 65th percentile — the lowest threshold among all BASICs). Unaddressed events are a leading indicator of roadside citations and accidents.

**14-day rule:** If coaching has not been acknowledged 14 days after it was assigned, this is no longer just a Samsara queue management issue — it is a **Level 1 trigger** (verbal counseling on failure to complete the coaching program). This is codified in the progressive discipline policy, Section 5. The 14-day clock runs from the date the events were flagged, not from when Audra saw the Teams card.

## 3. Decision Tree

| Occurrence in 30d | Signal in Teams card | Action required | Who acts |
|---|---|---|---|
| 1st (coaching open / Needs Disposition) | No badge | Open/complete coaching session | Audra via Samsara |
| 2nd occurrence in 30d or 14d+ unacked | ⚠️ 2nd in 30d | Verbal warning (Level 1 → Level 2) | Audra |
| 3rd in 30d | 🔴 3rd in 30d | Written warning | Audra → Jeff drafts |
| 4th+ in 30d | 🚨 #N in 30d | Escalate to JB immediately | Audra → JB |
| 14 days unacknowledged (any count) | Days-open indicator | Level 1 verbal counseling on failure to complete coaching program | Audra |

**Distinction:** The occurrence count in the accountability system tracks how many times this driver has appeared on the coaching list within 30 days. The 14-day rule is a separate, parallel trigger that fires when the events in a single appearance have sat unacknowledged too long.

## 4. Action Scripts

**Coaching Needed — open and complete the session:**

First step is always to complete the coaching session in Samsara, not to call the driver. Open the event in Samsara, review the footage, determine whether the event is valid (coach) or invalid (dismiss). If valid, open the coaching session and make contact with the driver.

**1st occurrence coaching conversation:**

> "I want to go over the safety event Samsara flagged for you on [date] — [brief description: e.g., 'a following-distance event on I-80']. I watched the footage. [Specific feedback: 'You were about 2 seconds behind the car ahead; our standard is 4+ seconds at highway speed.'] I'm logging this as reviewed in Samsara. Going forward, [specific behavior expected]. Any questions?"

**14-day unacknowledged — Level 1 verbal counseling:**

> "The coaching session for the [event type] flagged on [date] has been open for 14 days without completion. Per our safety program, coaching sessions must be completed in a timely way. I'm noting this as a Level 1 verbal counseling — failure to complete the coaching program — in your file. The session needs to be completed by [date, 7 days out]. If there's a reason you weren't able to get to it, let me know."

**2nd occurrence — Verbal Warning (Level 2):**

> "This is the second time in 30 days that you've appeared on the coaching needs list. Per our progressive discipline policy, this is a verbal warning — I'm documenting this conversation in your file. A third occurrence within 30 days requires a written warning. Samsara coaching isn't optional — it's how we track and address safety patterns that protect you and keep our CSA score clean. What's making it hard to complete these sessions?"

**3rd occurrence — Written Warning (Level 3):**

> Jeff drafts the letter. Subject line: "[Driver first name]". Cite the specific event types, the dates of the prior two appearances on the coaching list, and the expected behavior change. Audra files original in Sharefile → incident file → by year → by driver. Jeff and JB retain working copies.

**4th+ — Escalate:**

Contact JB Sweere directly. JB determines next step.

## 5. Documentation

Record for every level:

- Date(s) of the safety events.
- Event type(s) (harsh braking, following distance, etc.).
- Date coaching session was opened and completed (or remains open).
- Date of coaching conversation / verbal / written warning.
- Expected behavior change.
- Driver signature (for Level 2+) or "driver declined to sign, [date]".
- Filed: Sharefile → incident file → [year] → [driver name].
- CC Jeff and JB on Level 3+.

## 6. Decision Points

- **If the Samsara event appears invalid (camera malfunction, road debris, false positive):** Dismiss the event in Samsara with a note. Document the dismissal. The driver does not need to be coached on an invalid event, but the dismissal is itself the completion of the disposition.
- **If the driver can't access Samsara to review the footage:** Audra should screen the footage and describe it in the coaching conversation. The platform access issue is separate from the coaching obligation.
- **If multiple drivers have open coaching sessions simultaneously:** Prioritize by: (a) days unacked (14+ days first), (b) event severity (harsh events first), (c) occurrence count on the list. Don't let the queue build — an unworked backlog is a CSA exposure.
- **If the underlying events are all speeding-related:** This driver may simultaneously appear on the [[Playbook — Speeding]] radar. Check the speed page. If the speeding flag is at a high threshold (>=2.5%), the speeding playbook's discipline entry point may be higher than the coaching playbook's — apply the more serious level.
- **If the CSA Unsafe Driving BASIC is approaching 65th percentile:** Accelerate discipline — flag to JB immediately.

## 7. Escalation

- **JB Sweere:** 4th+ occurrence; unresolved 14-day backlog across multiple drivers; Unsafe Driving BASIC approaching 65th percentile.
- **Jeff Hannahs:** Level 3 written warning draft; CC on Level 3+.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** If a driver's safety event pattern creates insurance exposure or Great West requests information. Insurance override supersedes internal discipline.

## 8. Connections

- [[Coaching Ack]] — technical detail on how ack state is derived from SafetyEvents `coachingStatus`, not the broken CoachingSessions sheet.
- [[Progressive Discipline Policy]] — 14-day coaching backlog = Level 1 trigger; 5-level framework; Samsara coaching backlog → discipline mapping (Section 5).
- [[Safety Program]] — coaching threshold (2 events), monitor vs. assign-coaching split, 3-day closeout window.
- [[FMCSA CSA Scorecard]] — Unsafe Driving BASIC percentile threshold (65th).
- [[Playbook — Speeding]] — overlapping trigger when coaching events are speed-related.
- [[Driver Roster]] — active drivers; check OO vs. Truk-Way track for discipline track selection.
- [[Key People]] — Audra Newman (owner), Jeff Hannahs (drafts letters), JB Sweere (Level 4+).

## 9. Recent Runs *(append-only)*

No runs logged yet.
