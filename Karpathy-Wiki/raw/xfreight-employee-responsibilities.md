# XFreight employee responsibilities — accountability map (seed 2026-06-14)

> Core memory. Source: operator decision 2026-06-14 establishing the
> role-focused brief delivery model. Captures who owns what across
> XFreight ops + finance + sales/recruiting + safety, and which
> briefs each person receives. Any future work on brief routing,
> playbook owner fields, risk-register owner fields, or org
> communication should reference this page first.

## The accountability map

| Person(s) | Owns | Receives (primary) | CC on |
|---|---|---|---|
| **Audra** | Safety + Compliance · invoice closeout (loads invoiced timely + carrier invoices entered into Alvys) | Safety & Compliance brief (daily) | — |
| **Jackson + Dan** | On-time delivery · truck coverage / return loads · drivers hitting 2,750 mi/wk average · driver dispatching · maintenance on trailers + Truk-Way tractors · overall brokerage (X-Linx) operations | Operational / Maintenance brief (daily) | — |
| **Jeff + JB** | Accounting / financial · sales · recruiting | Accounting / financial brief (daily); Sales brief (weekly); Recruiting brief (weekly) — Jeff primary on sales/recruiting, JB cc | All non-owned briefs (governance visibility) |
| **Dan + JB + Jeff** | Consolidated executive view | Executive brief (X-Trux + X-Linx, daily) | — |

## Brief routing rules (canonical)

Every brief built by this codebase routes to its owner(s) first, with
Jeff + JB cc'd unless they're already the primary. Concretely:

- **Executive brief** (`scorecard_email.py` → `scorecard_email.yml`)
  → Dan, JB, Jeff. The consolidated 13-page view; no role drill-down.
- **Safety & Compliance brief** (`safety_compliance_email.py` →
  `safety_compliance_email.yml`) → **Audra** primary; Jeff, JB cc.
  *(Currently in jeff-only test mode — flip to this distribution
  when ready.)*
- **Operational / Maintenance brief** (not yet built) → **Jackson,
  Dan** primary; Jeff, JB cc. On-time %, coverage status, return-load
  gaps, per-driver mileage vs 2,750 target, MPG / idle / maintenance
  drill-downs.
- **Accounting / Financial brief** (not yet built) → **Jeff, JB**.
  Bill matching, QB reconciliation, AR per-customer trend,
  cash-flow forecasting. Accounting tiles remain in the executive
  brief so Dan keeps awareness — this is the deeper drill-down.
- **Sales brief** (weekly, not yet built) → **Jeff** primary; JB cc.
  Customer concentration trend, RFP pipeline status, contract
  expirations 60/90/180 days out, win/loss against bids.
- **Recruiting brief** (weekly, not yet built) → **Jeff** primary;
  JB cc. Driver hiring pipeline by stage, hires/separations MTD,
  MVR risk on new hires, days-to-fill on open seats. (Audra continues
  to own MVR/license tracking on existing drivers in the Safety brief.)

## Responsibility detail per role

### Audra — Safety, Compliance, Invoice closeout

- All safety events, HOS violations, DVIR defects, coaching workflow.
- Driver MVR + license + medical-card monitoring (SambaSafety +
  Alvys Drivers sheet).
- DOT inspection scheduling for trucks + trailers
  (see `xfreight-dot-inspection-policy.md` for the 120d company
  policy / 365d federal rule). All inspection costs paid by X-Trux.
- **Invoice closeout** — making sure every delivered load is
  invoiced timely (customer side) and that every carrier invoice
  is entered into Alvys (brokered-side). Slippage here drags AR
  aging and Power BI's accuracy.

### Jackson + Dan — Operations / Maintenance / Brokerage ops

- **On-time delivery** — every load delivered within the customer's
  appointment window. Drives customer relationships and rate
  retention.
- **Truck coverage / return loads** — every truck has a return load
  back to a region where another customer load can be grabbed. No
  empty bobtail home unless unavoidable.
- **Driver mileage target** — average **2,750 miles per week** per
  driver. Drives revenue, driver pay, and driver retention (drivers
  leave when their miles are short).
- **Driver dispatching** — load assignment, route planning, driver
  communication during transit, handling appointment changes.
- **Maintenance — trailers** — scheduling and tracking trailer
  repairs, tire/brake/light condition, replacement decisions. All
  trailers across the fleet.
- **Maintenance — Truk-Way tractors** — the leased-out tractor fleet
  (Truk-Way is the leasing entity). Coordination with the OO-group
  drivers, repair scheduling, vendor relationships.
- **Overall X-Linx brokerage operations** — day-to-day brokerage
  execution: booking loads, finding carriers to cover, negotiating
  carrier rates, tracking brokered loads in transit, escalating
  carrier issues. Strategic brokerage BD / customer relationships
  still sit with Jeff + JB; Jackson + Dan run the operational side.
- Coordinates with Audra on the safety-side DOT inspection
  scheduling (Audra owns the 120d company-policy compliance angle;
  Jackson + Dan own the broader maintenance program). See
  `xfreight-dot-inspection-policy.md` for the inspection split.

### Jeff + JB — Finance, Sales, Recruiting

- All accounting / financial decisions: P&L, AR collections,
  factoring partner, cost-out, RPM goal, capital decisions.
- All sales: customer relationships at the VP+ level, RFP pricing,
  contract negotiations, customer escalations beyond the dispatch
  level.
- All recruiting: hiring decisions, OO-group lease decisions,
  separations.
- JB has signoff on consequential decisions (rate concessions
  >5%, separations, factoring switches, contracts >$200K/yr,
  capital expansion).
- Jeff leads day-to-day BD execution.

### Dan + JB + Jeff — Consolidated leadership

- Receive the executive brief so the operational picture and the
  financial picture stay aligned. Daily.
- JB + Jeff are cc'd on every owner-specific brief above for
  governance visibility — they don't act on them day-to-day but see
  what's happening.

## Cadence summary

- **Daily** (every morning 5am CT): Executive, Safety & Compliance,
  Operational / Maintenance, Accounting / Financial.
- **Weekly** (Monday morning): Sales pipeline, Recruiting pipeline.
- All briefs use the same DST-proof dual-cron + CT-hour-gate
  pattern documented in `xfreight-data-pipeline-architecture.md`.

## How this changes existing code

- Risk-register entries and playbook frontmatter `owner:` fields
  should match this canonical map. Audit existing pages and update
  any that are stale.
- New brief workflows (operational, accounting, sales, recruiting)
  follow the same recipient-fallback pattern as `scorecard_email.yml`:
  GitHub secret for the standing list with a hardcoded literal as
  the last `||` fallback so the brief always reaches the right
  audience even if a secret gets emptied.
- The Slack/Teams digest (`slack_digest.py`) should support
  per-channel routing when Phase 3B lands — each brief type posts
  to its owners' channel, not a single firehose.

## Related

- `xfreight-daily-scorecard-email.md` — current executive brief.
- `xfreight-key-people.md` — bios + contact details for each
  person listed above.
- `xfreight-slack-teams-digest.md` — the delivery surface that
  will use this map for routing in Phase 3B.
