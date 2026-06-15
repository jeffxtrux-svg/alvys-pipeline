# Driver report — per-driver wishlist (captured 2026-06-15)

> **Status:** Wishlist / not yet built. Captured from Jeff on the drive
> home 2026-06-15. Second wishlist item from the same conversation
> (after the OTD early-warning page in
> `xfreight-otd-early-warning-wishlist.md`).
>
> This is a **first** for XFreight's brief stack — every existing brief
> goes to management. This one goes **to the drivers themselves.**

## What Jeff wants

A **per-driver report** sent to each driver showing where they stand
on every dimension that matters to their day-to-day and their
paycheck. One report per driver, personalized — not a fleet-wide blast.

Content buckets Jeff named:

- **Where they're sitting** — current location / status / next
  appointment / load they're on.
- **Operating** — miles last week, settlement-week pace, on-time
  delivery record, idle %, MPG vs the fleet.
- **Safety** — their Samsara safety score, coaching items open or
  closed, recent events, DVIR status, license / medical / MVR
  expirations on the horizon.
- **"Everything"** — and an **overall report card** that pulls it all
  together so the driver sees their own snapshot the way the office
  sees them.

## Why this is high-leverage

- **Drivers are the first non-management audience** in the brief
  stack — opens a new product surface.
- **Retention lever.** Drivers leave when they feel invisible or
  miscounted. A personalized weekly snapshot they trust is a
  retention asset.
- **Safety + coaching closeout.** Drivers who can see their own
  safety trajectory respond faster to coaching items than drivers
  who hear about it second-hand through dispatch.
- **Dan-aligned.** Dan is the most driver-connected leader; he'll
  be the natural sponsor / QA reviewer for what goes on the report
  (see `xfreight-dan-tracking-and-driver-connection.md`).

## Data sources (already in the pipeline)

Every piece exists today — this report is a **rearrangement** of data
already on other briefs, not a new pull.

- **Where they're sitting** — Samsara live location + Alvys trip /
  next-stop fields (same sources as the OTD early-warning page).
- **Miles + settlement week** — Alvys driver mileage by settlement
  week, already computed for Operational brief page 7
  (`build_page4`).
- **MPG + idle + speed** — already computed for Operational pages 8
  + 9 (`build_page_fleet`, `build_page_idle`).
- **Safety score** — already pulled per-driver in
  `samsara_client.fetch_driver_safety_scores` and rendered on Safety
  brief page 4 (`build_page2b`).
- **Coaching items + DVIR** — Safety brief page 3 (`build_page2`).
- **License / medical / MVR** — Safety brief page 2 (`build_page9`),
  sourced from SambaSafety + Alvys Drivers sheet.

## Open scoping questions

1. **Cadence.** Daily, weekly, or both (daily nudge + weekly deep
   summary)? Weekly aligned with settlement week is the natural
   default since pay is weekly.
2. **Delivery channel.** Email? Text (drivers more likely to read on
   phone)? In-cab tablet? Samsara driver app push? Each has different
   tradeoffs on richness vs reach.
3. **Format.** PDF attachment like the management briefs, or a
   simpler HTML email body / mobile-friendly card? Drivers won't open
   a 13-page PDF — likely needs to be a 1-page card.
4. **Personalization scope.** Driver-only data, or include
   fleet-relative context (e.g., "your MPG is 6.8 — fleet avg is
   6.4, you're in the top quartile")? The relative framing is more
   motivating but also more sensitive.
5. **Action surface.** Does the report ASK the driver to do something
   (acknowledge a coaching item, confirm a fact) or is it read-only?
   Read-only is simpler; actionable closes more loops.
6. **Opt-out / privacy.** Are drivers obligated to receive this, or
   opt-in? What gets escalated to dispatch if a driver doesn't
   open / respond?
7. **Pay alignment.** Driver pay data lives in Alvys settlements —
   include a settlement-week pay summary, or keep pay out of this
   report and stick to operational / safety only? (Higher trust ask
   but very high engagement value.)
8. **Audience confirmation.** All drivers? OO + company drivers
   equally, or different reports per type (X-Trux OO vs Truk-Way
   company drivers have different metrics that matter)?

## Product owner / QA

- **Sponsor:** Dan (driver-connected; will own the relationship
  question).
- **Safety-data QA:** Audra (owns the safety inputs, will catch
  drift between this report and the Safety brief).
- **Build sequencing:** depends on the OTD early-warning page +
  Operations brief landing first, since this report consumes from
  them.

## Next steps

- Hold for Jeff's answers to the scoping questions above.
- Loop Dan in once scoping is settled — he's the natural sponsor.
- This is **phase 3+** in the brief roadmap (after OTD page on
  Executive brief, then Operations brief).
