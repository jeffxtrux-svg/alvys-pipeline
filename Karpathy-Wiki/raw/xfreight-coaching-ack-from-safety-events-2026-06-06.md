# Coaching ack derivation switched to SafetyEvents (2026-06-06)

> Source: this conversation. Confirmed via GitHub Actions log of
> samsara_refresh run 27044437937 (5:57 PM CT 2026-06-05) + screenshots
> from Jeff of the Samsara Coaching > Completed tab showing Michael Hall's
> May 29 Self-Coaching session marked Completed.

## The bug

The page-1 "Coaching needs assigned" table was showing em-dash in the **Ack**
column for **every** driver in the "Assign coaching" tier, forever. Michael
Hall completed his Harsh Brake self-coaching session in Samsara on
**2026-05-29** — eight days before the 2026-06-06 brief — and per the
visibility rule (`_ACK_KEEP_DAYS = 3`) should have dropped off the list
on June 1. Instead he was still on the list with em-dash on June 6.

## The root cause

Samsara's `/coaching/sessions` REST endpoint **returns HTTP 404 on every
run**. It has since the feature was first wired. Per `samsara_refresh` log
27044437937:

```
22:59:42 ERROR   src.samsara_client: GET /coaching/sessions failed [404]: 404 page not found
22:59:42 WARNING src.samsara_client: GET /coaching/sessions → HTTP 404 — skipping (check API token scope)
22:59:42 INFO    src.samsara_client: Total coaching sessions: 0
22:59:42 INFO    src.samsara_client: Fetching training assignments…
22:59:42 ERROR   src.samsara_client: GET /training/assignments failed [404]: 404 page not found
22:59:53 WARNING samsara_main:   CoachingSessions: no data — writing placeholder sheet
```

`_safe_get` swallowed the 404 (correctly, by design — fail soft on optional
data), the CoachingSessions sheet got written as a 1-row placeholder, and
`compute_samsara` built `out["coaching_acks"] = {}` on every run. The
render's `_ack_after(driver, event_ts)` lookup always returned None, so the
ack column was always em-dash.

## Why the brief still shows `status = coached` on safety events

Samsara's coaching-completion state is recorded on each **safety event**
itself (the `coachingStatus` field — values include `coached`,
`needsRecognition`, `dismissed`, `recognized`). That field IS captured
in the SafetyEvents sheet and IS rendered on the page-1 "Safety events —
last 7 days" Status column. The data was always present — we just weren't
using it as the ack source.

The proper endpoint (per Samsara docs) is
`GET /coaching/driver-coach-assignments` for coach-to-driver mapping; there
is no public "list completed sessions" endpoint. Coaching completion per
event is reconstructed from safety-event `coachingStatus` + `coachedAtTime`
+ `coachedBy.name`. The Training Assignments stream
(`GET /training-assignments/stream`) is beta and must be enabled by
Samsara's CSM.

## The fix

`src/scorecard_email.py compute_samsara` now builds per-driver ack state
directly from the SafetyEvents sheet during the `coaching_list` aggregator
loop:

- `all_coached` = `True` only if every event for that driver in the 30-day
  window has status in `{coached, dismissed, recognized}`.
- `ack_ts` = the latest `coachedAtTime` across that driver's coached
  events, falling back to the event's own time if `coachedAtTime` isn't
  populated.
- `coach` = the most-frequent `coachedBy.name` across that driver's coached
  events (defensively column-probed under several name aliases since
  Samsara's `json_normalize` shape isn't fully documented).

`_safety_detail_tables` consumes those three new fields per row instead of
the (always-empty) `coaching_acks` dict. The visibility rule is unchanged
(`_ACK_KEEP_DAYS = 3` after ack), and a new **Coach** column is rendered
between Action and Ack.

The dead `coaching_acks` builder and `_ack_after` helper were removed.
The CoachingSessions past-due block in `compute_samsara` is kept (defensive)
in case the endpoint comes back online or moves.

## Expected output after the fix

Using Jeff's screenshots from 2026-06-06 as the reference:

| Driver | Action | Coach | Ack |
|---|---|---|---|
| MICHAEL HALL | Assign coaching | Audra Heidelberger | ✓ (until 6/1 + 3 = drops by 6/4) |
| GARY ABLA | Assign coaching | Audra Heidelberger | — (until all 3 events flip to coached) |
| Joseph Hanson | Assign coaching | depends on event status | — until acked |

The "all events coached" rule was Jeff's explicit choice (over "any" or
"latest only") so the brief reflects whether the driver fully closed out
the window, not a partial cleanup.

## Open thread for future iteration

- The Samsara `coachedBy.name` field is captured defensively via
  `_find_col(_7d, ["coachedby.name", "coached by", "coachedby"])`. The
  exact column name in our flattened SafetyEvents sheet is unconfirmed
  from this remote env; if the Coach column reads em-dash in the next
  brief even though Samsara has a coach assigned, the column-name probe
  needs to be extended.
- The Samsara endpoint situation should be revisited: the right paths are
  `/coaching/driver-coach-assignments` (Read Coaching scope) and
  `/training-assignments/stream` (beta + Read Training scope). Both need
  scope changes on the static bearer token and the training stream needs
  Samsara CSM enablement. Until then, this safety-event-derived ack is
  the source of truth.

## Related

- `xfreight-recent-decisions-2026-06-05.md` § "Driver acknowledgment column
  on safety events" — describes the original (broken) design that this
  page supersedes.
- `connector-samsara.md` (docs/knowledge-base/) — should be updated next
  time to reflect this ack-derivation change.
