# Samsara coaching attribution — endpoint investigation

The scorecard's safety section labels each event with its `coachingState`
(coached / dismissed / recognized / needsRecognition). What's been
deliberately missing is **who coached it** — the manager's name. This
page records every Samsara API endpoint we probed for that data, what
came back, and the workaround that ships today.

## The ask

For every Samsara safety event where a manager has taken action, show
the manager's first name (or full name) on the scorecard so the reader
can see *who* is doing the coaching, not just that it happened.

## RESOLUTION ATTEMPT (2026-06-08) — still blocked

Samsara support pointed to **`assignedCoach`** on `/fleet/safety-events`
([v2 reference](https://developers.samsara.com/reference/getsafetyeventsv2))
as the user id of whoever's assigned to coach the event. They also
confirmed `coachedBy.{id,name}` will NOT be added (and
`/fleet/safety-events/{id}` will continue to return 404 — that's
intentional platform design).

We wired it up in `samsara_main.py` (read `assignedCoach` per event, look
the user id up in the `Users` sheet, set `coachedBy.{id,name}` on the raw
event) and added a probe in `samsara_client.fetch_safety_events`.

**Result on the production tenant (XFreight, 97 safety events / 190d):**

- `assignedCoach` present on **0 / 97** events in the default response.
- The complete set of top-level keys on a coached event is exactly:
  `behaviorLabels, coachingState, downloadForwardVideoUrl,
  downloadInwardVideoUrl, driver, id, location, maxAccelerationGForce,
  time, vehicle`. No `assignedCoach`, no `coachedBy`, no `actor`,
  no `user`, no `review`.
- Re-fetched with `?include=assignedCoach`, `?include=coachedBy`, and
  `?include=assignedCoach,coachedBy` — **all three returned the exact
  same 10-key response shape.** The `include=` parameter is silently
  ignored by Samsara on this endpoint for our tenant.

So the wiring on our side is correct but it merges `coachedBy` onto 0
events because the upstream field never appears. Coach attribution is
**still blocked.**

Likely causes (in decreasing order of probability):
1. **Pre-assignment never set in the Samsara dashboard.** `assignedCoach`
   is the *pre-assigned* coach for a safety event, not the person who
   actually closed it. If no one has been designated in the dashboard,
   the field is omitted from the response. Coaching-state changes
   continue to happen via the dashboard's coach-flow buttons (which is
   why `coachingState` flips to `coached/dismissed/recognized`), but
   the actor isn't recorded anywhere queryable.
2. **API token scope.** Our daily-pull token may not include whatever
   scope exposes the field. Documentation doesn't enumerate scopes.
3. **Tenant feature flag.** Samsara may gate the field behind a tier
   our XFreight account doesn't have.

Status of the wiring: the `assignedCoach → coachedBy.{id,name}` merge
stays in place — it's harmless on 0 events and lights up automatically
the moment Samsara starts returning the field. The probe in
`samsara_client.fetch_safety_events` stays too so we can detect the
moment it flips on.

Next step on the user side: either (a) go back to Samsara support with
this evidence (`include=` silently ignored; field absent on every
coached event including ones with explicit coaching activity in the
audit-log), or (b) assign coaches to events in the Samsara dashboard
to see whether that populates the field on the next pull.

## What we have today

The Samsara `/fleet/safety-events` list endpoint returns these keys per
event (confirmed by diagnostic probe in `samsara_client.fetch_safety_events`):

```
behaviorLabels, coachingState, downloadForwardVideoUrl,
downloadInwardVideoUrl, driver, id, location,
maxAccelerationGForce, time, vehicle
```

No `coachedBy`, no `reviewedBy`, no `actor`, no `user`. Just the
event itself and the state the coaching workflow is in.

The audit-log feed (see below) adds **when** a coaching state change
happened per event, but not by whom.

So the scorecard knows everything about each event **except who acted
on it.**

## Endpoint matrix — what we tried

All probes were run against the production XFreight Samsara tenant
using the daily-pull API token.

| Endpoint | HTTP method | Result | Carries coach attribution? |
|---|---|---|---|
| `/fleet/safety-events` | GET (list) | 97 events / 190d | ❌ No `coachedBy` field in any of 97 records |
| `/fleet/safety-events?include=coachedBy&expand=coachedBy` | GET (list, expanded) | Same 97 events | ❌ Params silently ignored; same shape as default |
| `/fleet/safety-events/{id}` | GET (v2 detail) | **HTTP 404** | ❌ Detail endpoint not enabled for our tenant — every event id 404s |
| `/v1/fleet/safety/events/{id}` | GET (v1 detail fallback) | **HTTP 404** | ❌ Same — v1 detail also missing |
| `/fleet/safety-events/audit-logs/feed` | GET (change-log) | **440 records / 190d** ✅ | ❌ Carries event id + time + type, but **no actor** on any record (incl. coaching types) |
| `/v1/fleet/safety/events/audit/feed` | GET (v1 audit fallback) | Empty | n/a |
| `/fleet/safety-events/stream` | GET (v2 stream — probed) | TBD | Pending — see "Stream endpoint" below |
| `/v2/fleet/safety-events` | GET (v2 path variant — probed) | TBD | Pending |
| `/coaching/sessions` | GET | HTTP 404 (long-standing) | ❌ Endpoint not exposed |
| `/training/assignments` | GET | HTTP 404 (long-standing) | ❌ Endpoint not exposed |

## Audit-log feed: what we DO get

`GET /fleet/safety-events/audit-logs/feed?startTime=ISO` returns
**440 records over 190 days** with this shape:

```json
{
  "id": "1764532691754617-281474980077702-1764532509739",
  "time": "2025-11-30T19:58:11.754Z",
  "type": "CoachingStateActivityType",
  "safetyEvent": {
    "id": "281474980077702-1764532509739",
    "driver": {"id": "4487424"},
    "vehicle": {"id": "281474980077702"},
    "behaviorLabels": [
      {"type": "FollowingDistance", "name": "Following Distance"}
    ],
    "time": "2025-11-30T19:55:09.739Z"
  }
}
```

Three record types observed in the 190-day window:

| Type | Count | What it represents |
|---|---|---|
| `CoachingStateActivityType` | 247 | A coach / dismiss / recognize action happened on the event |
| `CreateSafetyEventActivityType` | 136 | Samsara auto-created the event |
| `BehaviorLabelActivityType` | 57 | Samsara auto-tagged the behavior |

**Key fact:** `CoachingStateActivityType` records carry `id`, `safetyEvent`,
`time`, `type` — and that's it. No `user`, no `actor`, no `performedBy`,
no `coachedBy`. The audit log records that a state change happened on
event X at time T, but not by whom.

## How the daily pipeline uses what's available

`src/samsara_main.py` now does two things with the audit log:

1. **Indexes coaching activity by event id.** For each
   `CoachingStateActivityType` record, takes the latest `time` per
   `safetyEvent.id` and stores it in a dict.
2. **Merges `coachedAtTime` onto the corresponding safety event** before
   the SafetyEvents sheet is written. The flattened sheet gains a new
   column "coachedAtTime" that the scorecard reads.

`src/scorecard_email.py` consumes this on the new **Coached Events**
end-of-brief page (`build_page_coached`):

- One row per safety event whose `coachingState` is
  coached / dismissed / recognized over the 190-day window.
- Columns: Driver, Unit, Event date, **Coached at** (from the new
  audit-log column), Event type, Severity, State.
- Sorted newest-coached-first.
- **Coach column intentionally absent** — there's no source for it
  today. Page footer carries a note explaining why.

The scorecard's existing `coachedBy.{name,id}` probes in
`compute_samsara` and `_safety_detail_tables` remain in place. The
moment any Samsara endpoint starts returning that field, the
status-cell suffix on the Safety Events table (page 1) and the Coach
column on the Coaching-needs-assigned table both light up automatically
— no code change required. The Coached Events page can be extended to
add a Coach column at the same time.

## What's been ruled out

The bottom of the response surface — every documented Samsara safety
endpoint that could plausibly carry coach attribution has been probed
and confirmed not to:

- **List endpoint** (`/fleet/safety-events`): no `coachedBy`.
- **Detail endpoints** (v2 and v1): return 404 — feature appears
  disabled for our tenant entirely.
- **Audit log feed**: carries the action, not the actor.
- **Legacy coaching/training endpoints**: 404.

The Samsara dashboard *does* display the coach name in the UI when you
view a coached event, so the data exists on Samsara's side — it's just
not exposed in the public API tier our account currently has.

## Paths forward (none enabled yet)

| Path | What it requires | Effort |
|---|---|---|
| **Samsara support ticket** | Ask Samsara to expose `coachedBy` on the safety-events list response or enable the per-event detail endpoint. Likely a paid feature or scope upgrade. | Out-of-band |
| **Webhooks** | Subscribe to Samsara webhook events for safety-event coaching actions. The webhook payload may carry the actor. Requires a public ingress endpoint to receive callbacks. | Days of work |
| **API scope upgrade** | The current API token may not have the "Read Safety Coaching" or similar scope. Check token permissions in the Samsara dashboard. | Minutes |
| **Manual capture** | Have whoever coaches log it (name, date, event) into a sheet the scorecard reads. Defeats the automation. | Ongoing |

If/when one of these unblocks attribution, the wiring is already in
place — the scorecard auto-populates the Coach column with no scorecard
code change. Just need the upstream feed.

## Code references

- `src/samsara_client.py`:
  - `fetch_safety_events()` — list endpoint, 190-day window
  - `fetch_safety_audit_log()` — audit-log feed, 190-day window
  - `fetch_safety_event_detail()` — confirmed dead, kept for retry
  - `fetch_safety_events_stream()` — v2 stream probe
- `src/samsara_main.py`: audit-log indexing + `coachedAtTime` merge
- `src/scorecard_email.py`:
  - `compute_samsara()` — builds `coached_events` list
  - `build_page_coached()` — renders the new end-of-brief page
- `docs/knowledge-base/connector-samsara.md` — broader Samsara connector
  notes (auth, pagination, sheet layout)
