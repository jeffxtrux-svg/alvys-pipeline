# XFreight Decision Journal — seed (2026-06-13)

Source-of-record for the compiled `wiki/decision-journal.md`. The point of this
log is to capture *why* a decision was made and *what we expected*, so that
later we can grade it — separating good judgment from luck. Each entry has a
predicted outcome; the "actual" line is filled in once it's known. **Assumptions
and predicted outcomes below need Jeff's review/calibration.**

## 2026-06-13 — X-Trux P&L hold-out at ≥74% Corrected Margin
- **Decision:** exclude X-Trux loads that are status "Open" OR have Corrected
  Margin % = (Revenue − Driver Rate)/Revenue ≥ 74% from the entity P&L.
- **Rationale:** those are office loads brokered to outside carriers with a tiny
  placeholder driver rate; counting them inflates own-fleet P&L.
- **Assumption:** ≥74% margin reliably identifies brokered/under-costed loads.
- **Predicted outcome:** brief P&L matches Power BI to the penny and reflects
  true own-fleet economics.
- **Actual:** _TBD — watch for genuine high-margin own-fleet loads wrongly held out._

## 2026-06-13 — Deadhead / RPM scoped to own-fleet only
- **Decision:** deadhead %, asset RPM, and mileage tiles count X-Trux own-fleet
  loads only (exclude X-Linx AND brokered X-Trux).
- **Rationale:** deadhead is empty miles *your own trucks* drive; carrier-driven
  loads aren't your deadhead.
- **Predicted outcome:** 5.448% true own-fleet deadhead (vs 4.90% when brokered
  loads were still in).
- **Actual:** _TBD._

## 2026-06-12 — Retire SambaSafety API, switch to CSV-drop
- **Decision:** after the API token expired 2026-06-02, retire API mode and read
  the CSVs Power Automate drops into OneDrive.
- **Rationale:** API access lapsed; CSV covers driver compliance + CSA needs
  without renewal cost.
- **Assumption:** the Power Automate CSV drop stays reliable.
- **Predicted outcome:** driver-compliance and CSA data keep flowing.
- **Actual:** _TBD — review ~2026-07-12 whether CSV drops have been reliable._
  (Paired risk: "SambaSafety CSV-drop fragility" in the risk register.)

## 2026-06-13 — Next oil change shown as a 25k estimate
- **Decision:** show estimated next-oil-due mileage (current odometer → next 25k
  mark, labeled "est") rather than wait for real odometer-at-service capture.
- **Rationale:** deliver visible value now; the page auto-flips to a real value
  when Alvys starts logging the odometer at each oil change.
- **Predicted outcome:** the estimate is close enough to be useful in the interim.
- **Actual:** _TBD when real oil-odometer data exists._

## Standing rule — dispatch date locks the per-mile pay rate
- **Decision:** driver per-mile pay rate is revised weekly on Wednesday; a load's
  dispatch date determines which week's rate applies (Tuesday dispatch → prior
  rate, Wednesday → new rate).
- **Rationale:** an unambiguous rule for which rate a load pays, for settlement.
- **Predicted outcome:** consistent settlement, no rate disputes.
- **Actual:** in effect; treated as confirmed.

## 2026-05-01 — Renewed insurance with Acrisure (+$0.08–0.10/mi)
- **Decision:** renew X-Trux / X-Linx insurance with Acrisure (Great West Casualty
  underwriter) effective May 1, 2026, accepting a ~$0.08–0.10/mi premium increase.
- **Rationale:** keep coverage continuity; no better-priced option lined up in time.
- **Predicted outcome:** the increase is absorbed into the cost-out so the
  rate-per-mile goal stays whole.
- **Actual:** renewal completed 5/1/26; increase figured into the costing (overhead
  pin $0.98 — confirm it fully reflects $0.08–0.10/mi). Outcome **confirmed**.
- **Forward:** evaluate an alternative broker/carrier before the next renewal — a
  different option may be needed down the road. (Jeff, 2026-06-13.)

## 2026-01 — AGCO 2026 truckload RFP (closed loop, graded)
- **Decision:** bid the AGCO 2026 truckload RFP.
- **Outcome:** NOT awarded (Jan 2026). Graded: lost. Lessons for the next cycle
  are captured in the AGCO RFP wiki page — kept here as an example of a decision
  with a known result, so the journal shows the full loop.
