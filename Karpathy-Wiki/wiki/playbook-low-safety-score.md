---
title: Playbook — Low Safety Score
type: playbook
tags: [playbook, safety, compliance, samsara, safety-score, driver, accountability, unsafe-driving]
status: active
owner: "Audra Newman (Safety & AP)"
last_revised: "2026-06-17"
trigger: "Brief's Teams card shows a Low Safety Score item for a driver — Samsara composite safety score below threshold"
related: ["[[Progressive Discipline Policy]]", "[[Safety Program]]", "[[FMCSA CSA Scorecard]]", "[[Coaching Ack]]", "[[Playbook — Coaching Needed]]", "[[Playbook — Speeding]]", "[[Driver Roster]]", "[[Key People]]"]
sources: ["raw/xfreight-accountability-playbooks.md", "raw/xfreight-progressive-discipline-policy.md", "raw/xfreight-safety-program.md"]
---

# Playbook — Low Safety Score

## 1. When to Run

Run this playbook when the Teams morning card or the daily email (page 3 — per-driver Samsara safety scores) shows a Low Safety Score flag for a driver. A low safety score means the driver's Samsara composite score has fallen below the threshold across a rolling window of safety events.

A low safety score is a pattern indicator, not a single event. It tells you that this driver has accumulated enough safety events (harsh braking, following too close, distracted driving, hard cornering, speeding) to pull their composite score below the acceptable floor. The coaching conversation is about the pattern, not any one event.

## 2. What This Means

Samsara calculates a per-driver composite safety score from all inward- and outward-facing camera events, telematics events, and driver performance metrics over a rolling window. The score reflects the cumulative picture of driving behavior — a single bad event affects the score, but a consistently low score indicates a systemic behavior pattern.

No 49 CFR regulation directly mandates a minimum "safety score." However, the underlying events that drive the score down — harsh braking, hard cornering, following-distance violations, distracted driving, speeding — feed directly into the **CSA Unsafe Driving BASIC** (intervention threshold: 65th percentile, the lowest threshold among all BASICs). A driver with a consistently low Samsara score is generating the kind of events that, if they trigger roadside citations, will move the Unsafe Driving BASIC. That BASIC's 65th percentile threshold is lower than any other BASIC's intervention point, meaning CSA exposure from Unsafe Driving accumulates faster.

**Technical note on the data source:** Fleet avg safety score comes from Samsara's per-driver safety-score endpoint. The `/fleet/drivers/{id}/safety/score` path 404s for XFreight's account; the `/v1/fleet/drivers/{id}/safety-score` legacy path is used. Scores are computed by Samsara over their rolling period.

## 3. Decision Tree

| Occurrence in 30d | Signal in Teams card | Action required | Who acts |
|---|---|---|---|
| 1st | No badge / "1st" | Coach (review which events are dragging the score) | Audra |
| 2nd | ⚠️ 2nd in 30d | Verbal warning | Audra |
| 3rd | 🔴 3rd in 30d | Written warning | Audra → Jeff drafts |
| 4th+ | 🚨 #N in 30d | Escalate to JB immediately | Audra → JB |

**Overlap with Coaching Needed:** A driver with a low safety score almost always also appears on the [[Playbook — Coaching Needed]] list. Check whether coaching sessions are open and acked — if unacknowledged coaching is contributing to the low score, both playbooks are in effect. Apply the more serious discipline level of the two.

**Overlap with Speeding:** If the low score is driven primarily by speeding events, check the [[Playbook — Speeding]] page-4 threshold — the speeding playbook's entry point may be higher (Level 2 minimum for >=3% speeding) than this playbook's. Apply the higher level.

## 4. Action Scripts

**1st — Coach (Level 1):**

> "I want to go over your Samsara safety score — it's below our threshold at [score]. I've reviewed the events driving it down. The main ones I'm seeing are [describe: e.g., 'three following-distance events and two harsh braking events over the last 30 days']. Let me show you [specific event or footage if available]. The pattern I'm trying to address is [describe]. Going forward, I want you to focus on [specific behavior change: e.g., 'maintaining at least 4 seconds of following distance at highway speed']. I'll check back in 30 days. Any questions?"

**2nd — Verbal Warning (Level 2):**

> "Your safety score is still below threshold — this is the second time in 30 days we've had to flag it. Per our progressive discipline policy, this is a verbal warning. I'm documenting this in your file now. A third flag within 30 days requires a written warning. Your score needs to get above [threshold] and stay there. I want to understand what's making it hard. What are you seeing out there that's triggering these events?"

**3rd — Written Warning (Level 3):**

> Jeff drafts the letter. Subject line: "[Driver first name]". Reference the Samsara safety score, the specific event categories driving it down, the dates of the prior coaching and verbal warning, and the expected improvement target and timeline. Audra files original in Sharefile → incident file → by year → by driver. Jeff and JB retain working copies.

**4th+ — Escalate:**

Contact JB Sweere directly. JB determines next step (load suspension for OO; unpaid suspension for Truk-Way employee; or insurance notification).

## 5. Documentation

Record for every level:

- Date of the safety score flag.
- Driver name, truck number, Samsara safety score at time of flag.
- Top event categories contributing to the low score.
- Date and content of coaching/warning conversation.
- Expected behavior change and target score.
- Review date: 30 days.
- Driver signature (Level 2+) or "driver declined to sign, [date]".
- Filed: Sharefile → incident file → [year] → [driver name].
- CC Jeff and JB on Level 3+.

## 6. Decision Points

- **If the low score is driven by a single large event (e.g., a serious crash):** The score reflects the event, but the playbook action should focus on the underlying incident. A crash may have its own discipline entry point (preventable accidents enter at Level 3 minimum per the progressive discipline policy). Run the appropriate playbook for the incident type alongside this one.
- **If the driver disputes the Samsara events:** Review the camera footage together. If an event is clearly a false positive (e.g., camera triggered by a pothole), dismiss it in Samsara with a note. Disputed events that cannot be disproved are addressed as valid.
- **If the score is low primarily due to events from a specific truck or route:** May indicate a vehicle issue (e.g., suspension causing false harsh-braking events) or a route characteristic. Investigate before issuing discipline. Document the investigation outcome.
- **If the CSA Unsafe Driving BASIC is approaching 65th percentile:** Accelerate discipline — the Unsafe Driving BASIC's intervention threshold is the lowest (65th percentile), so exposure accumulates faster here than in any other BASIC. Flag to JB immediately.
- **If multiple drivers have low safety scores simultaneously:** Look for a fleet-wide pattern. Is there a dispatch timing pressure? A specific customer lane driving harder behavior? Address the root cause at the fleet level with a memo from Audra.

## 7. Escalation

- **JB Sweere:** 4th+ occurrence; Unsafe Driving BASIC approaching 65th percentile; pattern of low scores across multiple drivers.
- **Jeff Hannahs:** Level 3 written warning draft; CC on Level 3+.
- **Jami Hewitt / Acrisure (jhewitt@acrisure.com):** If a driver's safety score pattern creates insurance exposure, or if Great West requests information. Insurance override supersedes internal discipline at any level.

## 8. Connections

- [[Playbook — Coaching Needed]] — typically co-triggered with Low Safety Score; a driver with a low score usually also has open coaching events. Run both; apply the higher discipline level.
- [[Playbook — Speeding]] — speeding events heavily influence safety score; if speeding is the primary driver of the low score, the speeding playbook's entry levels may be higher.
- [[Coaching Ack]] — how coaching ack state is derived from Samsara SafetyEvents `coachingStatus`, not the CoachingSessions sheet.
- [[Progressive Discipline Policy]] — 5-level framework; Samsara coaching backlog → discipline mapping.
- [[FMCSA CSA Scorecard]] — Unsafe Driving BASIC (65th percentile threshold — the most sensitive BASIC).
- [[Safety Program]] — per-driver safety scores page (page 3/4 of brief), speed rubric, coaching needs assigned list.
- [[Driver Roster]] — active drivers; check OO vs. Truk-Way track.
- [[Key People]] — Audra Newman (owner), Jeff Hannahs (drafts letters), JB Sweere (Level 4+), Jami Hewitt (insurance).

## 9. Recent Runs *(append-only)*

No runs logged yet.
