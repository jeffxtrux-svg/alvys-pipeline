---
title: Coaching Ack — SafetyEvents Derivation (2026-06-06 Fix)
type: concept
tags: [safety, samsara, coaching, pipeline, bug-fix]
sources: ["raw/xfreight-coaching-ack-from-safety-events-2026-06-06.md"]
related: ["[[Safety Program]]", "[[Daily Scorecard Email]]", "[[Recent Decisions 2026-06-05]]"]
---

# Coaching Ack — SafetyEvents Derivation

On June 6, 2026, the coaching-acknowledgment logic in `src/scorecard_email.py` was rewritten to derive ack state from the SafetyEvents sheet rather than the CoachingSessions sheet. This page documents the bug, root cause, fix, and open items.

## Summary

The **Ack** column on the "Coaching needs assigned" table was always showing em-dash for every driver in the "Assign coaching" tier. The root cause was that Samsara's `/coaching/sessions` REST endpoint returns HTTP 404 on every run. The fix: derive ack state directly from each safety event's `coachingStatus` field on the SafetyEvents sheet, which is populated correctly.

## The Bug

Michael Hall completed his Harsh Brake self-coaching session in Samsara on **2026-05-29** — eight days before the 2026-06-06 brief. Per the `_ACK_KEEP_DAYS = 3` rule he should have dropped off the list by June 1. Instead he was still listed with an em-dash Ack on June 6.

## Root Cause

Samsara's `/coaching/sessions` endpoint returns HTTP 404 on every run:

```
ERROR   src.samsara_client: GET /coaching/sessions failed [404]: 404 page not found
WARNING src.samsara_client: GET /coaching/sessions → HTTP 404 — skipping
INFO    src.samsara_client: Total coaching sessions: 0
```

`_safe_get` swallowed the 404 (correctly — fail soft on optional data), the CoachingSessions sheet was written as a 1-row placeholder, and `compute_samsara` built `out["coaching_acks"] = {}` on every run. The `_ack_after(driver, event_ts)` lookup always returned None, so the Ack column was always em-dash.

## Why the Data Was Always There

Samsara records coaching-completion state on each **safety event** itself via the `coachingStatus` field. Values: `coached`, `needsRecognition`, `dismissed`, `recognized`. This field IS captured in the SafetyEvents sheet and IS rendered in the "Safety events — last 7 days" Status column — the data was always present, just not used as the ack source.

The proper Samsara endpoint for coaching is `GET /coaching/driver-coach-assignments` (for coach-to-driver mapping). There is no public "list completed sessions" endpoint. The Training Assignments stream (`GET /training-assignments/stream`) is beta and must be enabled by Samsara's CSM.

## The Fix

`compute_samsara` now builds per-driver ack state directly from SafetyEvents during the `coaching_list` aggregator loop:

- `all_coached` = `True` only if **every** event for that driver in the 30-day window has status in `{coached, dismissed, recognized}`.
- `ack_ts` = the latest `coachedAtTime` across that driver's coached events, falling back to the event's own timestamp if `coachedAtTime` isn't populated.
- `coach` = the most-frequent `coachedBy.name` across that driver's coached events (probed defensively under several column-name aliases).

`_safety_detail_tables` consumes those three new fields per row instead of the (always-empty) `coaching_acks` dict. Visibility rule unchanged (`_ACK_KEEP_DAYS = 3` after ack). A new **Coach** column was added between Action and Ack.

The dead `coaching_acks` builder and `_ack_after` helper were removed. The CoachingSessions past-due block in `compute_samsara` is kept (defensive) in case the endpoint comes back online.

## Expected Output (Post-Fix)

Jeff's June 6, 2026 screenshots as the reference:

| Driver | Action | Coach | Ack |
|---|---|---|---|
| MICHAEL HALL | Assign coaching | Audra Heidelberger | ✓ (until 6/1 + 3 = should drop by 6/4) |
| GARY ABLA | Assign coaching | Audra Heidelberger | — (until all 3 events flip to coached) |
| Joseph Hanson | Assign coaching | depends on event status | — until acked |

The "all events coached" rule was Jeff's explicit choice (over "any" or "latest only") — the brief reflects whether the driver fully closed out the window, not a partial cleanup.

## Policy Detail: Two-Tier Coaching List

This fix does not change the two-tier visibility policy (established in PR #86 + #88):

| Tier | Events | Behavior |
|---|---|---|
| **Monitor** | < 2 | Drops off 7 days after last event. Ack = "n/a". |
| **Assign coaching** | ≥ 2 | Stays until all events coached, then 3 more days. Shows Coach + Ack columns. |

## Open Items

- The `coachedBy.name` field is probed defensively via `_find_col(_7d, ["coachedby.name", "coached by", "coachedby"])`. If the Coach column reads em-dash in the next brief despite Samsara having a coach assigned, the column-name probe needs to be extended.
- The Samsara endpoint situation should be revisited: the right paths are `/coaching/driver-coach-assignments` (Read Coaching scope) and `/training-assignments/stream` (beta + CSM enablement). Until then, SafetyEvents-derived ack is the source of truth.

## Supersedes

The original PR #86 design (`coaching_acks` dict from CoachingSessions + `_ack_after`) is described in [[Recent Decisions 2026-06-05]] § "PR #86 — Driver Acknowledgment Column on Safety Events." That design was broken from day one and this fix replaces it entirely.

## Connections

- [[Safety Program]] — coaching policy, speed rubric, MVR workflow.
- [[Daily Scorecard Email]] — Ack column appears on page 1 and page 3.
- [[Recent Decisions 2026-06-05]] — original (broken) PR #86 design documented there.

## Sources

- `raw/xfreight-coaching-ack-from-safety-events-2026-06-06.md`
