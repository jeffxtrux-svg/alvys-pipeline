"""Generate XFreight Safety & Compliance Program overview PDF."""

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @page {
    size: letter;
    margin: 0.6in 0.7in 0.6in 0.7in;
    @bottom-center {
      content: "XFreight Safety & Compliance Program — Confidential";
      font-family: Arial, sans-serif;
      font-size: 8pt;
      color: #888;
    }
    @bottom-right {
      content: counter(page) " of " counter(pages);
      font-family: Arial, sans-serif;
      font-size: 8pt;
      color: #888;
    }
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: Arial, sans-serif;
    font-size: 10.5pt;
    color: #1a1a2e;
    line-height: 1.55;
  }

  /* ── COVER ── */
  .cover {
    page-break-after: always;
  }
  .cover-stripe {
    background: #1a3a6b;
    color: white;
    padding: 52px 48px 44px;
    margin-bottom: 36px;
  }
  .cover-logo {
    font-size: 13pt;
    font-weight: bold;
    letter-spacing: 2px;
    color: #aac4e8;
    text-transform: uppercase;
    margin-bottom: 20px;
  }
  .cover-title {
    font-size: 28pt;
    font-weight: bold;
    line-height: 1.2;
    color: #ffffff;
  }
  .cover-subtitle {
    font-size: 13pt;
    color: #aac4e8;
    margin-top: 10px;
  }
  .cover-body { padding: 0 48px; }
  .cover-tagline {
    font-size: 13pt;
    color: #1a3a6b;
    font-style: italic;
    margin-bottom: 28px;
    line-height: 1.5;
  }
  .cover-meta {
    font-size: 9pt;
    color: #666;
    border-top: 1px solid #ddd;
    padding-top: 14px;
    margin-top: 32px;
  }
  .cover-pillars {
    display: flex;
    gap: 12px;
    margin-top: 28px;
  }
  .cover-pillar {
    flex: 1;
    background: #f0f5fb;
    border-left: 4px solid #1a3a6b;
    padding: 14px 14px;
    border-radius: 3px;
  }
  .cover-pillar-title {
    font-size: 9pt;
    font-weight: bold;
    color: #1a3a6b;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
  }
  .cover-pillar-text { font-size: 8.5pt; color: #444; }

  /* ── HEADINGS ── */
  h1 {
    font-size: 18pt;
    color: #1a3a6b;
    border-bottom: 2.5px solid #1a3a6b;
    padding-bottom: 6px;
    margin-bottom: 16px;
    margin-top: 0;
    page-break-after: avoid;
  }
  h2 {
    font-size: 12pt;
    color: #1a3a6b;
    font-weight: bold;
    margin-top: 22px;
    margin-bottom: 8px;
    page-break-after: avoid;
  }
  h3 {
    font-size: 10.5pt;
    color: #2a5298;
    font-weight: bold;
    margin-top: 14px;
    margin-bottom: 6px;
    page-break-after: avoid;
  }

  /* ── SECTIONS ── */
  .section {
    margin-bottom: 16px;
  }
  /* Keep section headings with the content that follows */
  .section h2, .section h3, .section h4 { page-break-after: avoid; }
  /* Tables stay intact (header + body together when possible) */
  table { page-break-inside: avoid; }

  p { margin-bottom: 9px; }
  ul, ol { margin: 8px 0 10px 22px; }
  li { margin-bottom: 4px; }

  /* ── CALLOUT BOXES ── */
  .callout {
    border-left: 4px solid #1a3a6b;
    background: #f0f5fb;
    padding: 12px 16px;
    margin: 14px 0;
    border-radius: 3px;
  }
  .callout-green {
    border-left: 4px solid #2e7d32;
    background: #f1f8f1;
  }
  .callout-amber {
    border-left: 4px solid #e65100;
    background: #fff8f0;
  }
  .callout-red {
    border-left: 4px solid #c62828;
    background: #fff5f5;
  }
  .callout-title {
    font-weight: bold;
    font-size: 9.5pt;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    margin-bottom: 5px;
    color: #1a3a6b;
  }
  .callout-green .callout-title { color: #2e7d32; }
  .callout-amber .callout-title { color: #e65100; }
  .callout-red   .callout-title { color: #c62828; }

  /* ── TABLES ── */
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0 16px;
    font-size: 9.5pt;
  }
  th {
    background: #1a3a6b;
    color: white;
    padding: 7px 10px;
    text-align: left;
    font-weight: bold;
    font-size: 9pt;
  }
  td {
    padding: 6px 10px;
    border-bottom: 1px solid #e0e0e0;
    vertical-align: top;
  }
  tr:nth-child(even) td { background: #f7f9fc; }
  tr:last-child td { border-bottom: 2px solid #1a3a6b; }

  /* ── METRIC TILES ── */
  .tiles { display: flex; gap: 10px; margin: 14px 0; }
  .tile {
    flex: 1;
    border: 1px solid #d0dce8;
    border-top: 3px solid #1a3a6b;
    padding: 12px 12px 10px;
    border-radius: 3px;
    text-align: center;
  }
  .tile-num {
    font-size: 22pt;
    font-weight: bold;
    color: #1a3a6b;
    line-height: 1;
  }
  .tile-label {
    font-size: 8pt;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
    line-height: 1.3;
  }
  .tile-green { border-top-color: #2e7d32; }
  .tile-green .tile-num { color: #2e7d32; }
  .tile-amber { border-top-color: #e65100; }
  .tile-amber .tile-num { color: #e65100; }
  .tile-red { border-top-color: #c62828; }
  .tile-red .tile-num { color: #c62828; }

  /* ── FLOW STEPS ── */
  .flow { margin: 14px 0; }
  .flow-step {
    display: flex;
    align-items: flex-start;
    margin-bottom: 10px;
  }
  .flow-num {
    background: #1a3a6b;
    color: white;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    font-size: 9pt;
    font-weight: bold;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-right: 12px;
    margin-top: 1px;
  }
  .flow-text { flex: 1; }
  .flow-text strong { color: #1a3a6b; }

  /* ── BADGE ── */
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 8pt;
    font-weight: bold;
  }
  .badge-red    { background: #fde8e8; color: #c62828; }
  .badge-amber  { background: #fff3e0; color: #e65100; }
  .badge-yellow { background: #fffde7; color: #f57f17; }
  .badge-green  { background: #e8f5e9; color: #2e7d32; }
  .badge-blue   { background: #e3f0fb; color: #1a3a6b; }

  .header-bar {
    background: #1a3a6b;
    color: white;
    padding: 6px 14px;
    font-weight: bold;
    font-size: 9.5pt;
    border-radius: 3px;
    margin-bottom: 12px;
    letter-spacing: 0.3px;
  }

  .two-col { display: flex; gap: 18px; }
  .two-col > div { flex: 1; }

  .small { font-size: 9pt; color: #555; }
  .caption { font-size: 8.5pt; color: #777; font-style: italic; margin-top: -8px; margin-bottom: 12px; }
</style>
</head>
<body>

<!-- ═══════════════════════════════════════════════════
     COVER
═══════════════════════════════════════════════════ -->
<div class="cover">
  <div class="cover-stripe">
    <div class="cover-logo">XFreight &nbsp;·&nbsp; X-Trux &nbsp;·&nbsp; X-Linx</div>
    <div class="cover-title">Safety &amp; Compliance Program</div>
    <div class="cover-subtitle">Technology-Powered Daily Accountability System</div>
  </div>
  <div class="cover-body">
    <p class="cover-tagline">
      A fully automated pipeline that ingests live data from Samsara, SambaSafety, and Alvys every morning, surfaces actionable safety intelligence to the right people, and tracks every item from identification through resolution — without spreadsheets, manual follow-up calls, or guesswork.
    </p>
    <div class="cover-pillars">
      <div class="cover-pillar">
        <div class="cover-pillar-title">Daily Visibility</div>
        <div class="cover-pillar-text">Every at-risk driver, unit, and compliance gap surfaces in a structured report every morning at 5 am CT.</div>
      </div>
      <div class="cover-pillar">
        <div class="cover-pillar-title">Real-Time Action</div>
        <div class="cover-pillar-text">Microsoft Teams cards let owners record actions the moment they're taken, with live ✅ updates every 30 minutes.</div>
      </div>
      <div class="cover-pillar">
        <div class="cover-pillar-title">Smart Suppression</div>
        <div class="cover-pillar-text">Items disappear from future briefs once actioned — and refire automatically if the underlying issue persists.</div>
      </div>
      <div class="cover-pillar">
        <div class="cover-pillar-title">CSA Protection</div>
        <div class="cover-pillar-text">Every action item maps directly to a FMCSA BASIC category, protecting X-Trux's carrier scorecard.</div>
      </div>
    </div>
    <div class="cover-meta">
      Prepared by XFreight Operations &nbsp;·&nbsp; Safety &amp; Compliance Division &nbsp;·&nbsp; Confidential<br>
      <strong>Living Document</strong> — Revision 1.1, June 2026 &nbsp;·&nbsp; Phases 1–3 complete
    </div>
  </div>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 2 — TABLE OF CONTENTS + EXECUTIVE SUMMARY
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>Executive Summary</h1>
  <p>
    XFreight operates a technology-first Safety &amp; Compliance program built on the premise that safety problems don't become violations — or worse, accidents — when they're caught and resolved the same day they appear. The program ingests live data from three integrated systems every morning, constructs a ranked list of compliance action items, delivers a structured daily brief to every responsible party by 5 am Central, and posts interactive accountability cards to Microsoft Teams that track each item from identification through resolution.
  </p>
  <p>
    Prior to this system, safety monitoring was reactive: a DOT inspection overdue notice might sit in an inbox for days; a driver's CDL suspension might not surface until a roadside check; coaching events from Samsara might age without follow-up. The current system eliminates that gap. Every identified risk has a named owner, a timestamped action log, and an automated escalation path if it isn't resolved within the prescribed window.
  </p>

  <div class="tiles">
    <div class="tile">
      <div class="tile-num">5 am</div>
      <div class="tile-label">Daily brief delivery (Central time)</div>
    </div>
    <div class="tile tile-green">
      <div class="tile-num">30 min</div>
      <div class="tile-label">Teams card refresh interval</div>
    </div>
    <div class="tile tile-amber">
      <div class="tile-num">11</div>
      <div class="tile-label">Compliance categories monitored daily</div>
    </div>
    <div class="tile tile-red">
      <div class="tile-num">3</div>
      <div class="tile-label">Live data sources (Samsara · SambaSafety · Alvys)</div>
    </div>
  </div>

  <div class="callout callout-green">
    <div class="callout-title">Core Objective</div>
    Zero tolerance for unresolved safety items older than 24 hours. Every action item has an owner, a window, and an automated escalation path. When an item is resolved, it is logged, marked complete, and suppressed from future briefs — returning only if the underlying condition recurs.
  </div>
</div>

<div class="section">
  <h1>Program Scope</h1>
  <p>The Safety &amp; Compliance program covers the full X-Trux and X-Linx fleet and all drivers operating under XFreight authority. Truk-Way tractors are covered under X-Trux Inc. for all DOT inspection purposes. The program monitors compliance in eleven categories organized across four FMCSA BASIC domains:</p>

  <table>
    <tr><th>FMCSA BASIC Domain</th><th>Categories Monitored</th><th>Primary Owner</th></tr>
    <tr>
      <td><strong>Driver Fitness</strong></td>
      <td>CDL Disqualified, Driver License Expiring, DOT Medical Card Expiring</td>
      <td>Audra</td>
    </tr>
    <tr>
      <td><strong>Crash Indicator &amp; Unsafe Driving</strong></td>
      <td>Safety Event Coaching, Safety Event Needs Disposition, Low Safety Score, Speeding</td>
      <td>Audra + Jackson/Dan</td>
    </tr>
    <tr>
      <td><strong>Vehicle Maintenance</strong></td>
      <td>DOT Inspection Overdue (Tractor &amp; Trailer), DVIR Defects, DVIR Compliance</td>
      <td>Audra (tractors) + Jackson/Dan (trailers)</td>
    </tr>
    <tr>
      <td><strong>HOS Compliance</strong></td>
      <td>HOS Violations, Prior-Day Logs Not Certified</td>
      <td>Audra + Jackson/Dan</td>
    </tr>
    <tr>
      <td><strong>MVR / Background</strong></td>
      <td>MVR Violations, SambaSafety Risk Flag (high-risk leaderboard)</td>
      <td>Audra</td>
    </tr>
  </table>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 3 — DATA SOURCES
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>Data Sources &amp; Integration</h1>
  <p>The program pulls live data from three separate SaaS platforms that do not natively communicate with each other. A custom Python pipeline running on GitHub Actions normalizes and joins the data each morning before the brief is generated.</p>

  <div class="two-col">
    <div>
      <div class="header-bar">Samsara (Telematics)</div>
      <ul>
        <li>Real-time driver safety scores (0–100 scale)</li>
        <li>Safety events: harsh braking, harsh acceleration, harsh turning, forward collision, following distance, speeding</li>
        <li>Coaching session status (coached / dismissed / needs coaching)</li>
        <li>DVIR defect reports (open and unresolved)</li>
        <li>HOS log certification status</li>
        <li>Driver location and on-duty status</li>
        <li>Vehicle GPS and odometer readings</li>
      </ul>
      <p class="small">Refresh cadence: pulled at 5 am, 11 am, and 5 pm CT daily.</p>
    </div>
    <div>
      <div class="header-bar">SambaSafety (Compliance)</div>
      <ul>
        <li>CDL validity and disqualification status</li>
        <li>Driver license expiration dates</li>
        <li>MVR violation history and points</li>
        <li>Driver risk scores and high-risk leaderboard</li>
        <li>FMCSA CSA2010 carrier scorecard (BASIC percentiles for X-Trux DOT #841776)</li>
      </ul>
      <p class="small">Refresh cadence: CSV drops from Power Automate several times daily; processed at 1 am, 3 am, and every 2 hours from 4 am–6 pm CT.</p>
    </div>
  </div>

  <div class="header-bar" style="margin-top:16px;">Alvys (Transportation Management System)</div>
  <div class="two-col">
    <div>
      <ul>
        <li>Active truck and trailer roster with inspection due dates</li>
        <li>DOT Annual Inspection Due dates (120-day company policy)</li>
        <li>Driver roster with DOT Medical Card expiration dates</li>
        <li>Load and trip data (mileage, revenue, settlement)</li>
      </ul>
    </div>
    <div>
      <ul>
        <li>Carrier invoice status (closeout compliance)</li>
        <li>Maintenance records (oil changes, inspections)</li>
        <li>Driver pay settlements</li>
      </ul>
    </div>
  </div>
  <p class="small" style="margin-top:4px;">Refresh cadence: pulled at 4 am, 11 am, and 5 pm CT daily. Data is staged to OneDrive for Power BI consumption.</p>

  <div class="callout" style="margin-top:18px;">
    <div class="callout-title">Data Join Logic</div>
    The three data sources are joined by driver name. SambaSafety provides CDL/license/MVR data. Samsara provides behavioral and telematics data. Alvys provides medical card and equipment data. The morning pipeline normalizes all three into a unified set of action items before the brief is generated.
  </div>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 4 — DAILY BRIEF
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>Daily Safety Brief</h1>

  <p>
    Each morning at 5 am Central, a multi-page PDF safety brief is generated and emailed to the Safety Manager (Audra) on the TO line, with Jeff and JB copied for governance visibility. The brief is the authoritative daily record of XFreight's compliance posture and contains everything needed to identify, prioritize, and act on every open safety item.
  </p>

  <h2>Brief Structure (22 pages)</h2>

  <table>
    <tr><th>Section</th><th>Pages</th><th>Contents</th></tr>
    <tr><td><strong>Driver Compliance</strong></td><td>2</td><td>SambaSafety MVR + CDL status, DOT medical card expirations from Alvys</td></tr>
    <tr><td><strong>Safety &amp; Compliance Detail</strong></td><td>2</td><td>24h Samsara safety events, HOS violations, DVIR defects, coaching status</td></tr>
    <tr><td><strong>Per-Driver Safety Scores</strong></td><td>1</td><td>Samsara safety score per driver — speed violations, harsh events, trends</td></tr>
    <tr><td><strong>Equipment Compliance — Tractors</strong></td><td>1</td><td>Tractor inspection status: 120-day company policy vs. 365-day federal</td></tr>
    <tr><td><strong>Equipment Compliance — Trailers</strong></td><td>1</td><td>Trailer inspection status; Jackson + Dan ownership</td></tr>
    <tr><td><strong>Driver Mileage</strong></td><td>1</td><td>Settlement-week mileage by driver vs. 2,750 mi/wk target</td></tr>
    <tr><td><strong>Fleet Operations (MPG &amp; Speed)</strong></td><td>1</td><td>Fuel efficiency best/worst, speeders list</td></tr>
    <tr><td><strong>Fleet Idle</strong></td><td>1</td><td>All trucks ranked by idle %, idle hours, idle-gallon estimate</td></tr>
    <tr><td><strong>CSA Scorecard</strong></td><td>1</td><td>FMCSA BASIC percentile ranks for X-Trux Inc. (DOT #841776)</td></tr>
    <tr><td><strong>Action Items Summary</strong></td><td>1</td><td>Consolidated TODAY / THIS WEEK action items with owner, category, urgency</td></tr>
    <tr><td><strong>Carry-Forward &amp; Open Items</strong></td><td>1</td><td>Items open 2+ days; escalation flags for items open 3+ days</td></tr>
  </table>

  <h2>DOT Inspection Policy — Two Thresholds</h2>
  <p>The brief tracks equipment compliance at two distinct windows to give maximum lead time before federal deadlines:</p>
  <div class="two-col">
    <div class="callout">
      <div class="callout-title">120-Day Company Policy</div>
      XFreight's internal standard. A unit flagged here is <strong>past company policy but still federally legal</strong> to operate. The brief flags these as needing scheduling — not out of service.
    </div>
    <div class="callout callout-red">
      <div class="callout-title">365-Day Federal Standard</div>
      The FMCSA annual inspection rule. A unit past this threshold is <strong>out of service per federal law</strong> and cannot move. This almost never fires because the 120-day policy catches units 245 days earlier.
    </div>
  </div>

  <h2>Reliability — Defense-in-Depth Delivery</h2>
  <p>GitHub Actions' cron scheduler is best-effort and has silently dropped entire morning batches (notably June 8 and June 16, 2026). The brief uses a layered delivery architecture to ensure it arrives every morning:</p>
  <div class="flow">
    <div class="flow-step"><div class="flow-num">1</div><div class="flow-text"><strong>Primary cron — 5:00 am CT.</strong> The normal daily run. Sends the full brief PDF to Audra (TO) and Jeff / JB (CC).</div></div>
    <div class="flow-step"><div class="flow-num">2</div><div class="flow-text"><strong>Backup crons — 5:30 am and 6:30 am CT.</strong> Idempotency-guarded: each run checks whether a sent-marker exists in OneDrive before sending. If the 5 am slot fired, these skip silently.</div></div>
    <div class="flow-step"><div class="flow-num">3</div><div class="flow-text"><strong>6:00 am Healthcheck.</strong> A lightweight workflow checks whether the OneDrive marker exists. If absent, it dispatches the full brief workflow immediately and alerts the team.</div></div>
    <div class="flow-step"><div class="flow-num">4</div><div class="flow-text"><strong>Cloudflare Worker backstop — 5:30 am CT.</strong> A script running entirely outside GitHub's infrastructure dispatches the healthcheck via the GitHub API every morning. If GitHub's own cron drops the healthcheck, this layer recovers it.</div></div>
  </div>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 5 — TEAMS ACCOUNTABILITY
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>Microsoft Teams Accountability Cards</h1>

  <p>
    Alongside the email brief, the system posts per-owner Adaptive Cards to the <em>Safety &amp; Compliance</em> Teams channel. Unlike the email (which is a read-only PDF), the Teams cards are interactive: each action item has a <strong>📋 Record action</strong> button that opens a pre-filled Microsoft Form where the owner logs what they did. The form response is written to <em>Accountability Log.xlsx</em> in OneDrive via Power Automate — no Premium license required.
  </p>

  <h2>Card Design</h2>
  <p>Two cards are posted each morning: one for <strong>Audra</strong> (driver compliance, CDL/MVR/medical, equipment — tractors, coaching) and one for <strong>Jackson + Dan</strong> (dispatch, trailers, DVIR, HOS, speeding). Each card shows:</p>
  <ul>
    <li>A header tile with owner name, date, and a count of open vs. completed items</li>
    <li>Open items sorted by urgency: escalated items (3+ days open) first, then by severity (Critical → High → Medium)</li>
    <li>Escalation flags: <em>⚠️ Day N — ESCALATED</em> for items open 3+ days; <em>🚨 #N in 30d</em> for recurring patterns</li>
    <li>Severity badges: 🔴 Critical · 🟠 High · 🟡 Medium</li>
    <li>One <strong>📋 Record action</strong> button per item — pre-filled with date, category, severity, driver/unit, and detail</li>
  </ul>

  <h2>Real-Time Green Checkmarks</h2>
  <p>
    The cards are refreshed every 30 minutes from 7 am to 5:30 pm CT. When an owner submits a form response, the next refresh re-posts the card with that item shown in a <strong>green ✅ completed block</strong>. All items remain visible — open items stay at the top; completed items move to the bottom with a green background. There is no need to wait until tomorrow to see progress.
  </p>

  <div class="callout callout-green">
    <div class="callout-title">End-of-Day Summary Card</div>
    At approximately 5 pm CT, an End-of-Day summary card is posted showing how many items were actioned vs. still open. Items without a logged action are flagged in red. This creates natural daily accountability without requiring manual status meetings.
  </div>

  <h2>Microsoft Form Pre-Fill</h2>
  <p>
    The <em>Record action</em> button uses Microsoft Form's pre-fill URL feature to auto-populate eight fields so the owner only needs to type their action note:
  </p>
  <table>
    <tr><th>Field</th><th>Pre-Filled From</th></tr>
    <tr><td>Date</td><td>Today's date (Central time)</td></tr>
    <tr><td>Name</td><td>Owner (Audra for her card; blank for shared Jackson/Dan card)</td></tr>
    <tr><td>Driver / Unit</td><td>Item's driver name or unit number</td></tr>
    <tr><td>Category</td><td>Action item category (e.g., "DOT Medical Card")</td></tr>
    <tr><td>Severity</td><td>Critical / High / Medium</td></tr>
    <tr><td>Detail</td><td>Specific detail text from the item</td></tr>
    <tr><td>Days Open</td><td>Carry-forward count</td></tr>
    <tr><td>Occurrences (30d)</td><td>Recurrence count over 30 days</td></tr>
  </table>
  <p class="caption">The owner fills in only "Action Taken" and optional notes. Power Automate writes the row to Accountability Log.xlsx automatically.</p>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 6 — SUPPRESSION & ESCALATION
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>Accountability Tracking — Suppression &amp; Escalation</h1>

  <p>
    The system maintains a <strong>suppression registry</strong> (<code>OneDrive/Safety/suppression-registry.json</code>) that tracks which items have been actioned and prevents them from appearing in future briefs during the appropriate window. When the window expires, the item is checked against live data — if the underlying condition still exists, it refires automatically.
  </p>

  <h2>Per-Category Suppression Windows</h2>

  <table>
    <tr><th>Category</th><th>Window</th><th>Rule</th></tr>
    <tr>
      <td><span class="badge badge-red">Critical</span> CDL Disqualified</td>
      <td>Until reinstatement date</td>
      <td>If a reinstatement date is entered in the form Notes field, the item is suppressed until that specific date. Falls back to 1-day recheck if no date is provided.</td>
    </tr>
    <tr>
      <td><span class="badge badge-red">Critical</span> Driver License Expiring</td>
      <td>Until 3 days before expiry</td>
      <td>Suppressed after actioning. Reappears automatically in the final 3-day window and stays on every day until the license is renewed in SambaSafety.</td>
    </tr>
    <tr>
      <td><span class="badge badge-red">Critical</span> DOT Medical Card</td>
      <td>Until 3 days before expiry</td>
      <td>Same logic as Driver License — actioning suppresses it until the final 3-day countdown, then it persists until renewed in Alvys.</td>
    </tr>
    <tr>
      <td><span class="badge badge-amber">High</span> DOT Inspection — Tractor</td>
      <td>7 days</td>
      <td>7-day suppression when appointment is confirmed. <strong>Cannot be suppressed if unit is 365+ days since last inspection (federal OOS)</strong> — stays on the card every day until the inspection is completed and Alvys reflects the new date.</td>
    </tr>
    <tr>
      <td><span class="badge badge-amber">High</span> DOT Inspection — Trailer</td>
      <td>7 days</td>
      <td>Same as tractor. Federal OOS units are not suppressible.</td>
    </tr>
    <tr>
      <td><span class="badge badge-amber">High</span> HOS Violation</td>
      <td>1 day (per occurrence)</td>
      <td>Each HOS violation is a unique event. Actioning it removes it from tomorrow's card. A new violation the next day is a new item.</td>
    </tr>
    <tr>
      <td><span class="badge badge-amber">High</span> MVR Violation</td>
      <td>1 day</td>
      <td>Actioned (challenged or acknowledged) → gone tomorrow. Reappears if a new violation lands in SambaSafety.</td>
    </tr>
    <tr>
      <td><span class="badge badge-amber">High</span> DVIR Compliance</td>
      <td>7 days</td>
      <td>Coached on DVIR compliance → 7-day grace period. Refires if driver's compliance is still below 90% after 7 days.</td>
    </tr>
    <tr>
      <td><span class="badge badge-amber">High</span> Speeding</td>
      <td>7 days</td>
      <td>Coached on speeding → 7-day grace period. Refires if driver's speed-over-limit % is still ≥ 1% after 7 days.</td>
    </tr>
    <tr>
      <td><span class="badge badge-amber">High</span> Low Safety Score</td>
      <td>7 days</td>
      <td>Coaching plan started → 7-day grace. Refires if Samsara score is still below 90.</td>
    </tr>
    <tr>
      <td><span class="badge badge-amber">High</span> SambaSafety Risk Flag</td>
      <td>180 days</td>
      <td>Action plan filed for high-risk leaderboard driver → 6-month suppression. Reappears automatically after 180 days unless the driver's risk score has improved in SambaSafety.</td>
    </tr>
    <tr>
      <td><span class="badge badge-blue">Data-driven</span> Safety Event — Coaching Needed</td>
      <td>Never suppressed</td>
      <td>Driven entirely by Samsara coaching status. Disappears only when Samsara shows the event as coached or dismissed. No manual override needed.</td>
    </tr>
    <tr>
      <td><span class="badge badge-blue">Data-driven</span> DVIR Defect</td>
      <td>Never suppressed</td>
      <td>Driven by Samsara DVIR open-defect list. Disappears only when the defect is cleared and re-inspected clean in Samsara.</td>
    </tr>
  </table>

  <h2>Escalation Logic</h2>
  <p>Items that remain open across multiple days escalate automatically:</p>
  <div class="two-col">
    <div class="callout callout-amber">
      <div class="callout-title">Day 2 Open — Carry-Forward</div>
      Item shows <em>↩ Day 2 open</em> badge. Days open counter increments daily. The item sorts above all new (Day 1) items of the same severity.
    </div>
    <div class="callout callout-red">
      <div class="callout-title">Day 3+ Open — ESCALATED</div>
      Item shows <em>⚠️ Day N — ESCALATED</em> badge and sorts at the very top of the card, above all other items regardless of severity.
    </div>
  </div>
  <div class="callout callout-red" style="margin-top:12px;">
    <div class="callout-title">Recurrence Escalation (30-Day Window)</div>
    Items that appear multiple times within 30 days show a recurrence badge: <em>⚠️ 2nd in 30d</em> or <em>🚨 #3 in 30d</em>. At the third occurrence, severity auto-escalates to Critical regardless of the original severity level. This catches patterns before they become FMCSA violations.
  </div>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 7 — RESPONSIBILITIES & WORKFLOW
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>Roles &amp; Responsibilities</h1>

  <table>
    <tr><th>Person(s)</th><th>Role</th><th>Brief Received</th><th>Accountability Areas</th></tr>
    <tr>
      <td><strong>Audra</strong></td>
      <td>Safety Manager</td>
      <td>Safety Brief (5 am, TO) + Financial Brief (7 am)</td>
      <td>CDL / License / Medical Card compliance; Safety event coaching; Tractor inspections; MVR violations; SambaSafety risk flags; Invoice closeout</td>
    </tr>
    <tr>
      <td><strong>Jackson + Dan</strong></td>
      <td>Operations / Dispatch</td>
      <td>Safety Brief (5 am, shared Teams card)</td>
      <td>Trailer inspections; DVIR compliance; Driver HOS; Speeding coaching; Truk-Way tractor maintenance; On-time delivery; Driver coverage</td>
    </tr>
    <tr>
      <td><strong>Jeff + JB</strong></td>
      <td>Executive / Finance</td>
      <td>Safety Brief (5 am, CC); Executive Brief (daily); Financial Brief (7 am)</td>
      <td>Governance visibility; Accounting; Sales; Recruiting</td>
    </tr>
  </table>

  <div class="callout" style="margin-top:4px;">
    <div class="callout-title">Tractor Inspection — Split Ownership</div>
    X-Trux (owner-operator) tractors fall under Audra's lane only. Truk-Way fleet tractors are a <strong>shared responsibility</strong>: Audra for safety / CSA Maintenance BASIC, plus Jackson + Dan for day-to-day maintenance scheduling. Action items on Audra's card call this out explicitly when the tractor is a Truk-Way unit.
  </div>

  <h1 style="margin-top:28px;">Daily Workflow</h1>

  <div class="flow">
    <div class="flow-step"><div class="flow-num">1</div><div class="flow-text"><strong>4:00 am CT — Data refresh.</strong> Alvys, Samsara, and SambaSafety data is pulled and staged to OneDrive. Excel files are updated for Power BI.</div></div>
    <div class="flow-step"><div class="flow-num">2</div><div class="flow-text"><strong>5:00 am CT — Safety brief generated.</strong> Pipeline reads all three data sources, identifies action items, generates a 22-page PDF, emails to Audra (TO) / Jeff + JB (CC), posts Teams cards to the Safety &amp; Compliance channel, and writes today's accountability JSON to OneDrive.</div></div>
    <div class="flow-step"><div class="flow-num">3</div><div class="flow-text"><strong>7:00 am – 5:30 pm CT — Real-time Teams updates.</strong> Every 30 minutes, the refresh workflow reads Accountability Log.xlsx, detects newly submitted form responses, and re-posts the Teams cards with ✅ green marks on completed items. Suppression registry is updated simultaneously.</div></div>
    <div class="flow-step"><div class="flow-num">4</div><div class="flow-text"><strong>~5:00 pm CT — End-of-day summary.</strong> An EOD card is posted to Teams showing how many items were actioned vs. still open for each owner. Unresolved items are highlighted in red.</div></div>
    <div class="flow-step"><div class="flow-num">5</div><div class="flow-text"><strong>Next morning — Suppression applied.</strong> Items actioned yesterday are checked against the suppression registry. Suppressed items do not appear in today's brief unless their window has expired and the condition still exists in live data.</div></div>
  </div>

  <h2>Accountability Log</h2>
  <p>Every action recorded through the Teams card form is written to <strong>Accountability Log.xlsx</strong> in <code>OneDrive/Safety/</code> via Power Automate. The log is a permanent audit trail of every safety action taken. Columns include:</p>
  <ul>
    <li>Date (Central time), Name, Driver/Unit, Category, Severity, Detail, Days Open, Occurrences</li>
    <li>Action Taken (free text — what was done), Notes (optional)</li>
  </ul>
  <p>The log is the source of truth for the suppression registry, the EOD summary, and any future audit or compliance review.</p>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 8 — CSA & FMCSA
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>FMCSA CSA Scorecard Integration</h1>

  <p>
    The daily brief includes a dedicated page showing X-Trux Inc.'s (DOT #841776) current FMCSA BASIC percentile scores, sourced from the SambaSafety CSA2010 Preview Scorecard report. This gives the safety team visibility into exactly where the carrier stands relative to FMCSA intervention thresholds before a roadside inspection or compliance review occurs.
  </p>

  <table>
    <tr><th>BASIC Category</th><th>Intervention Threshold</th><th>What It Covers</th></tr>
    <tr><td>Unsafe Driving</td><td>≥ 65th percentile</td><td>Speeding, reckless driving, improper lane changes, inattention</td></tr>
    <tr><td>Crash Indicator</td><td>≥ 65th percentile</td><td>History of crashes weighted by severity and fault</td></tr>
    <tr><td>HOS Compliance</td><td>≥ 80th percentile</td><td>Log falsification, missing logs, HOS violations</td></tr>
    <tr><td>Vehicle Maintenance</td><td>≥ 80th percentile</td><td>Driver vehicle inspection reports, maintenance violations</td></tr>
    <tr><td>Controlled Substances / Alcohol</td><td>≥ 80th percentile</td><td>Drug/alcohol violations detected at roadside</td></tr>
    <tr><td>Hazardous Materials</td><td>≥ 80th percentile</td><td>HM permit and placard violations (if applicable)</td></tr>
    <tr><td>Driver Fitness</td><td>≥ 80th percentile</td><td>Invalid CDL, medical certificate violations</td></tr>
  </table>

  <div class="callout callout-amber">
    <div class="callout-title">How the Daily Program Protects the CSA Score</div>
    Every action item category in the daily accountability system maps directly to one or more FMCSA BASIC domains. Catching and resolving a CDL suspension the same day it appears prevents a roadside violation that would hit the Driver Fitness BASIC. Coaching a speeding driver within 24 hours reduces Unsafe Driving exposure. Clearing DVIR defects immediately prevents Vehicle Maintenance violations. The accountability system is, at its core, a CSA score protection mechanism.
  </div>

  <h2>Why 120 Days (Company Policy) vs. 365 Days (Federal)</h2>
  <p>
    XFreight operates on a <strong>120-day internal inspection cycle</strong> — more than twice as conservative as the federal 365-day standard. A unit would need to be 245 days past the company policy deadline before it reaches the federal out-of-service threshold. The reasons:
  </p>
  <ul>
    <li><strong>Driver safety</strong> — catching mechanical issues at 4 months vs. 12 months</li>
    <li><strong>CSA Maintenance BASIC protection</strong> — roadside inspections finding maintenance violations are devastating to the BASIC score</li>
    <li><strong>Equipment longevity</strong> — regular inspections catch wear before it becomes failure</li>
    <li><strong>No operational gap</strong> — units that reach the 365-day federal threshold are an immediate crisis requiring an emergency inspection before the truck moves. The 120-day policy eliminates this scenario entirely under normal operations.</li>
  </ul>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 9 — TECHNOLOGY ARCHITECTURE
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>Technology Architecture</h1>

  <div class="header-bar">Infrastructure Overview</div>
  <div class="two-col">
    <div>
      <h3>Pipeline (GitHub Actions)</h3>
      <ul>
        <li>Python 3.11 scripts running on GitHub-hosted runners</li>
        <li>Cron-scheduled with DST-proof dual-UTC-slot + Central-time gate pattern</li>
        <li>All sensitive credentials stored as GitHub Secrets (no plaintext anywhere)</li>
        <li>Output artifacts (PDF, Excel, JSON) retained 7 days for debugging</li>
        <li>Idempotent runs: a re-run at any time is safe and won't duplicate sends</li>
      </ul>
      <h3>Data Storage (OneDrive)</h3>
      <ul>
        <li>All staged Excel files stored in Microsoft OneDrive / SharePoint</li>
        <li>Daily accountability JSON: <code>Safety/accountability-{date}.json</code></li>
        <li>Suppression registry: <code>Safety/suppression-registry.json</code></li>
        <li>Accountability log: <code>Safety/Accountability Log.xlsx</code></li>
        <li>Brief sent-marker: <code>Safety/sent-{date}.txt</code> (idempotency)</li>
      </ul>
    </div>
    <div>
      <h3>External APIs</h3>
      <ul>
        <li><strong>Samsara API</strong> — safety events, driver scores, DVIR, HOS, vehicles</li>
        <li><strong>Microsoft Graph API</strong> — OneDrive read/write, email sending (no SMTP credentials needed)</li>
        <li><strong>Microsoft Teams Incoming Webhook</strong> — Adaptive Card posting</li>
        <li><strong>Microsoft Forms + Power Automate</strong> — accountability form responses → Excel log (no Premium license)</li>
        <li><strong>GitHub API</strong> — healthcheck workflow dispatch (via Cloudflare Worker)</li>
      </ul>
      <h3>Reliability Layer</h3>
      <ul>
        <li>Cloudflare Worker runs entirely outside GitHub's infrastructure</li>
        <li>Dispatches all three healthcheck workflows at 5:30 am CT daily</li>
        <li>Recovers the case where GitHub drops the healthcheck itself</li>
        <li>Zero cost (Cloudflare free tier)</li>
      </ul>
    </div>
  </div>

  <h2>Key GitHub Workflows</h2>
  <table>
    <tr><th>Workflow</th><th>Schedule (Central)</th><th>Purpose</th></tr>
    <tr><td>safety_compliance_email.yml</td><td>5:00 am (+ 5:30, 6:30 backups)</td><td>Generate brief, email PDF, post Teams cards</td></tr>
    <tr><td>safety_compliance_healthcheck.yml</td><td>6:00 am</td><td>Check OneDrive marker; dispatch brief if missed</td></tr>
    <tr><td>teams_refresh.yml</td><td>Every 30 min, 7 am – 5:30 pm</td><td>Re-post Teams cards with ✅ on newly actioned items; update suppression registry</td></tr>
    <tr><td>sambasafety_refresh.yml</td><td>Hourly, 1 am – 6 pm</td><td>Process SambaSafety CSV drops from Power Automate</td></tr>
    <tr><td>refresh.yml (Alvys)</td><td>4 am / 11 am / 5 pm</td><td>Pull Alvys data → OneDrive + Google Sheets</td></tr>
    <tr><td>samsara_refresh.yml</td><td>4 am / 11 am / 5 pm</td><td>Pull Samsara telematics data</td></tr>
  </table>

  <h2>Security &amp; Access Controls</h2>
  <ul>
    <li>All API credentials stored as encrypted GitHub Secrets — never in source code</li>
    <li>Microsoft Graph access uses a dedicated Azure app registration with least-privilege scopes</li>
    <li>OneDrive access scoped to a single user's drive (ONEDRIVE_USER_UPN)</li>
    <li>Teams webhook URL stored as secret; cannot be used to read data, only post messages</li>
    <li>No driver PII is written to GitHub repositories or build artifacts — all data stays in OneDrive</li>
  </ul>
</div>


<!-- ═══════════════════════════════════════════════════
     PAGE 10 — OUTCOMES & NEXT STEPS
═══════════════════════════════════════════════════ -->
<div class="section">
  <h1>Program Outcomes &amp; Goals</h1>

  <h2>What We Expect to Accomplish</h2>
  <p>The safety accountability program is designed to produce measurable improvements across four dimensions:</p>

  <div class="callout callout-green">
    <div class="callout-title">1. Zero Same-Day Unresolved Critical Items</div>
    <p>Every Critical-severity item (CDL suspended, medical card expired, federal OOS unit) should be actioned the same day it appears. The Teams card system, real-time ✅ updates, and EOD summary create the visibility and friction needed to achieve this.</p>
  </div>

  <div class="callout callout-green" style="margin-top:10px;">
    <div class="callout-title">2. Reduction in Days-Open Average</div>
    <p>The carry-forward counter and escalation badges create natural urgency. The target is for fewer than 10% of items to reach Day 3 (the escalation threshold). Items escalating to Day 3+ represent a process failure, not just a compliance gap.</p>
  </div>

  <div class="callout callout-green" style="margin-top:10px;">
    <div class="callout-title">3. CSA BASIC Score Improvement</div>
    <p>By resolving coaching events, DVIR defects, HOS violations, and driver fitness issues within 24 hours rather than days, the program aims to reduce X-Trux's exposure in every FMCSA BASIC category. A lower BASIC percentile means fewer targeted roadside inspections and lower insurance risk.</p>
  </div>

  <div class="callout callout-green" style="margin-top:10px;">
    <div class="callout-title">4. Full Audit Trail for Compliance Reviews</div>
    <p>Every action taken is logged in Accountability Log.xlsx with a timestamp, owner name, and description. In the event of an FMCSA compliance review or an insurance audit, XFreight can demonstrate that every identified safety issue was addressed promptly and systematically.</p>
  </div>

  <h2>Metrics to Track</h2>
  <table>
    <tr><th>Metric</th><th>Target</th><th>Source</th></tr>
    <tr><td>Critical items resolved same day</td><td>100%</td><td>Accountability Log.xlsx</td></tr>
    <tr><td>Items reaching Day 3 (escalated)</td><td>&lt; 10%</td><td>Accountability JSON carry-forward</td></tr>
    <tr><td>DVIR compliance rate (fleet avg)</td><td>≥ 95%</td><td>Samsara</td></tr>
    <tr><td>Driver avg safety score</td><td>≥ 90</td><td>Samsara</td></tr>
    <tr><td>Units past 120-day inspection policy</td><td>0</td><td>Alvys</td></tr>
    <tr><td>CDL / medical card violations at roadside</td><td>0</td><td>FMCSA DataQ / SambaSafety</td></tr>
    <tr><td>CSA Unsafe Driving BASIC</td><td>&lt; 65th percentile</td><td>SambaSafety CSA scorecard</td></tr>
    <tr><td>CSA Vehicle Maintenance BASIC</td><td>&lt; 80th percentile</td><td>SambaSafety CSA scorecard</td></tr>
  </table>

  <h2>Continuous Improvement Roadmap</h2>
  <p>This is a living program. Each phase builds on the last — what we learn in daily operations shapes what we automate next. The knowledge base, playbooks, and accountability data we accumulate over time are the foundation for every phase ahead.</p>

  <table style="width:100%; border-collapse:collapse; margin-top:14px; font-size:9.5pt;">
    <thead>
      <tr style="background:#1a3a6b; color:white;">
        <th style="padding:8px 10px; text-align:left; width:22%;">Phase</th>
        <th style="padding:8px 10px; text-align:left;">Capability</th>
        <th style="padding:8px 10px; text-align:center; width:15%;">Status</th>
      </tr>
    </thead>
    <tbody>
      <tr style="background:#f0f5fb;">
        <td style="padding:8px 10px; font-weight:bold; color:#1a3a6b;">Phase 1</td>
        <td style="padding:8px 10px;">Daily 5am brief · Teams accountability cards · 30-min refresh with green checkmarks · Accountability Log.xlsx · Smart suppression registry · Per-category escalation rules · EOD summary · Weekly trend report</td>
        <td style="padding:8px 10px; text-align:center; font-weight:bold; color:#2e7d32;">&#10003; Complete</td>
      </tr>
      <tr>
        <td style="padding:8px 10px; font-weight:bold; color:#1a3a6b;">Phase 2</td>
        <td style="padding:8px 10px;">90-day recurrence registry — same driver/category appearing 3+ times in 90 days triggers a <strong>🔁 Progressive discipline</strong> badge on the Teams card and flags the item for formal PD workflow. Coaching sessions open 5+ days without acknowledgment show a <strong>🔴 Supervisor follow-up required</strong> escalation.</td>
        <td style="padding:8px 10px; text-align:center; font-weight:bold; color:#2e7d32;">&#10003; Complete</td>
      </tr>
      <tr style="background:#f0f5fb;">
        <td style="padding:8px 10px; font-weight:bold; color:#1a3a6b;">Phase 3</td>
        <td style="padding:8px 10px;">CSA BASIC threshold alert — each morning after the scorecard CSV is processed, the system posts an immediate Teams alert if any BASIC reaches its FMCSA intervention threshold (Unsafe Driving/Crash Indicator ≥ 65th pct; all others ≥ 80th pct). Fires once per day via an OneDrive marker.</td>
        <td style="padding:8px 10px; text-align:center; font-weight:bold; color:#2e7d32;">&#10003; Complete</td>
      </tr>
      <tr>
        <td style="padding:8px 10px; font-weight:bold; color:#1a3a6b;">Phase 4</td>
        <td style="padding:8px 10px;">Power BI safety dashboard reading directly from Accountability Log.xlsx and Samsara data — real-time visibility, no need to wait for the 5am brief; slice by driver, category, date range, or owner</td>
        <td style="padding:8px 10px; text-align:center; color:#888;">Planned</td>
      </tr>
      <tr style="background:#f0f5fb;">
        <td style="padding:8px 10px; font-weight:bold; color:#1a3a6b;">Phase 5</td>
        <td style="padding:8px 10px;">Predictive risk scoring — combine SambaSafety risk flag trends, recurrence patterns, HOS frequency, and safety score trajectory to surface drivers at elevated risk before an incident occurs</td>
        <td style="padding:8px 10px; text-align:center; color:#888;">Future</td>
      </tr>
    </tbody>
  </table>

  <div class="callout" style="margin-top:20px;">
    <strong>Living Document Policy:</strong> This document is updated each time the program evolves — new capabilities, revised suppression rules, updated metrics targets, or lessons learned from the field. The generation script lives in the XFreight pipeline repository (<code>output/generate_safety_program_doc.py</code>) so any team member can regenerate the latest version at any time. Revision history is tracked in the repository's commit log.
  </div>
</div>

<div class="section" style="margin-top:32px; border-top:2px solid #1a3a6b; padding-top:18px;">
  <p class="small" style="text-align:center; color:#888;">
    XFreight Safety &amp; Compliance Program &nbsp;·&nbsp; X-Trux Inc. · X-Linx &nbsp;·&nbsp; Revision 1.1 — June 2026 &nbsp;·&nbsp; Confidential &amp; Proprietary<br>
    Questions: contact the Safety Manager or Operations leadership.
  </p>
</div>

</body>
</html>"""

from weasyprint import HTML as WP_HTML
from pathlib import Path

out = Path("output/XFreight_Safety_Compliance_Program.pdf")
out.parent.mkdir(exist_ok=True)
WP_HTML(string=HTML).write_pdf(str(out))
print(f"PDF written to {out} ({out.stat().st_size // 1024} KB)")
