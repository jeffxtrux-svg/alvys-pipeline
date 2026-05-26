// =============================================================================
// GoalTables — What-If parameter tables for XFreight KPI gauges
//
// In Power BI Desktop, create each table below using:
//   Modeling tab → New Parameter (What-If)
//
// These are used by the XFreight, Projections, and Page 2 report pages.
//
// OPTION A (recommended): Create as What-If parameters in Power BI Desktop
//   - Each becomes a slicer that lets you adjust goals dynamically
//
// OPTION B: Create as fixed DAX tables (paste into New Table)
//   - Simpler, but goals are hard-coded; need DAX edits to change them
// =============================================================================

// -----------------------------------------------------------------------
// Option A: What-If Parameter definitions (set these up via the UI)
// -----------------------------------------------------------------------
//
// 1. Goal Revenue Linx
//    Minimum:  $0,  Maximum: $5,000,000,  Increment: $50,000
//    Default:  $600,000   (adjust to your monthly target)
//
// 2. Goal Margin % Linx
//    Minimum:  0%,  Maximum: 100%,  Increment: 1%
//    Default:  18%
//
// 3. Goal Revenue Trux
//    Minimum:  $0,  Maximum: $2,000,000,  Increment: $25,000
//    Default:  $350,000
//
// 4. Goal Margin % Trux
//    Minimum:  0%,  Maximum: 100%,  Increment: 1%
//    Default:  25%
//
// 5. Empty Mileage Goal %
//    Minimum:  0%,  Maximum: 100%,  Increment: 1%
//    Default:  15%
//
// 6. Margin %  (used in Projections page)
//    Minimum:  0%,  Maximum: 100%,  Increment: 0.5%
//    Default:  20%
//
// 7. Days in Month  (used in Projections page)
//    Minimum:  1,  Maximum: 31,  Increment: 1
//    Default:  21   (working days)
//
// 8. Days Worked  (used in Projections page)
//    Minimum:  0,  Maximum: 31,  Increment: 1
//    Default:  0   (update each day)

// -----------------------------------------------------------------------
// Option B: DAX table definitions — paste each one into Modeling → New Table
// -----------------------------------------------------------------------
//
// Table: Goal Revenue Linx
//   Goal Revenue Linx = GENERATESERIES(0, 5000000, 50000)
//   (rename the column "Value" → "Goal Revenue Linx" in the column properties)
//
// Table: Goal Margin % Linx
//   Goal Margin % Linx = GENERATESERIES(0, 1, 0.01)
//
// Table: Goal Revenue Trux
//   Goal Revenue Trux = GENERATESERIES(0, 2000000, 25000)
//
// Table: Goal Margin % Trux
//   Goal Margin % Trux = GENERATESERIES(0, 1, 0.01)
//
// Table: Empty Mileage Goal %
//   Empty Mileage Goal % = GENERATESERIES(0, 1, 0.01)
//
// Table: Margin %
//   Margin % = GENERATESERIES(0, 1, 0.005)
//
// Table: Days in Month
//   Days in Month = GENERATESERIES(1, 31, 1)
//
// Table: Days Worked
//   Days Worked = GENERATESERIES(0, 31, 1)
//
// Table: WeekTable  (for the Report Delivery Date page)
//   WeekTable =
//     ADDCOLUMNS(
//       CALENDAR(DATE(2023,1,1), TODAY()),
//       "WeekLabel",
//           "WE " & FORMAT(
//               [Date] + (7 - WEEKDAY([Date], 2)),   -- next Sunday
//               "M/D"
//           ),
//       "WeekEnd",
//           [Date] + (7 - WEEKDAY([Date], 2))
//     )
