// Alvys Pipeline — personal PWA viewer.
// Fully client-side: parses Alvys_Master.xlsx in the browser, persists
// to IndexedDB, renders Loads / Trips / Fuel dashboards. No data leaves
// the device.

const APP_VERSION = "1.0.0";
const DB_NAME = "alvys-pipeline";
const DB_STORE = "data";
const DB_KEY = "current";
const URL_PREF_KEY = "alvys.defaultUrl";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ---------------------------------------------------------------------------
// IndexedDB helpers (single record cache of the last-loaded workbook)
// ---------------------------------------------------------------------------
function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(DB_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function saveData(payload) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DB_STORE, "readwrite");
    tx.objectStore(DB_STORE).put(payload, DB_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function loadData() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DB_STORE, "readonly");
    const req = tx.objectStore(DB_STORE).get(DB_KEY);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => reject(req.error);
  });
}

async function clearData() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(DB_STORE, "readwrite");
    tx.objectStore(DB_STORE).delete(DB_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

// ---------------------------------------------------------------------------
// XLSX parsing
// ---------------------------------------------------------------------------
async function parseXlsx(arrayBuffer, fileName) {
  if (typeof XLSX === "undefined") {
    throw new Error("Spreadsheet parser failed to load. Connect once to download it, then it works offline.");
  }
  const wb = XLSX.read(arrayBuffer, { type: "array" });
  const want = ["Loads", "Trips", "Fuel"];
  const out = {};
  for (const sheet of want) {
    if (!wb.SheetNames.includes(sheet)) {
      out[sheet.toLowerCase()] = [];
      continue;
    }
    out[sheet.toLowerCase()] = XLSX.utils.sheet_to_json(wb.Sheets[sheet], {
      defval: null,
      raw: true,
    });
  }
  return {
    fileName,
    loadedAt: new Date().toISOString(),
    loads: out.loads,
    trips: out.trips,
    fuel: out.fuel,
  };
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  data: null,           // { fileName, loadedAt, loads:[], trips:[], fuel:[] }
  currentTab: "dashboard",
  list: { type: null, search: "", status: "" },
};

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------
const fmtMoney = (n) => {
  const num = Number(n);
  if (!isFinite(num) || num === 0) return "$0";
  const sign = num < 0 ? "-" : "";
  const abs = Math.abs(num);
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
};

const fmtMoneyFull = (n) => {
  const num = Number(n);
  if (!isFinite(num)) return "—";
  return num.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
};

const fmtNum = (n) => {
  const num = Number(n);
  if (!isFinite(num)) return "—";
  return num.toLocaleString("en-US");
};

const fmtDate = (v) => {
  if (v == null || v === "") return "—";
  if (typeof v === "number") {
    // Excel serial date — SheetJS usually converts, but handle anyway
    const ms = (v - 25569) * 86400 * 1000;
    return new Date(ms).toLocaleDateString();
  }
  return String(v);
};

// MM-DD-YYYY from pipeline output → Date
function parsePipelineDate(s) {
  if (!s || typeof s !== "string") return null;
  const m = s.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})/);
  if (!m) return null;
  const [, mo, d, y] = m;
  return new Date(Number(y), Number(mo) - 1, Number(d));
}

function isWithinDays(dateStr, days) {
  const d = parsePipelineDate(dateStr);
  if (!d) return false;
  const ms = Date.now() - d.getTime();
  return ms >= 0 && ms <= days * 86400 * 1000;
}

const statusClass = (s) => {
  if (!s) return "";
  const v = String(s).toLowerCase();
  if (/(delivered|complete|paid|invoiced)/.test(v)) return "ok";
  if (/(transit|booked|dispatched|assigned)/.test(v)) return "warn";
  if (/(cancel|reject|fail|overdue|not\s?complete)/.test(v)) return "err";
  return "";
};

// ---------------------------------------------------------------------------
// View routing
// ---------------------------------------------------------------------------
function showView(name, opts = {}) {
  // Hide all
  for (const v of $$(".view")) v.classList.add("hidden");

  // Show requested
  if (name === "empty") {
    $("#view-empty").classList.remove("hidden");
    $("#view-title").textContent = "Alvys";
    setActiveTab("dashboard");
    return;
  }
  if (name === "dashboard") {
    $("#view-dashboard").classList.remove("hidden");
    $("#view-title").textContent = "Dashboard";
    setActiveTab("dashboard");
    renderDashboard();
    return;
  }
  if (name === "settings") {
    $("#view-settings").classList.remove("hidden");
    $("#view-title").textContent = "Settings";
    setActiveTab("settings");
    renderSettings();
    return;
  }
  if (name === "list") {
    $("#view-list").classList.remove("hidden");
    const type = opts.type || state.list.type;
    state.list.type = type;
    $("#view-title").textContent = capitalize(type);
    setActiveTab(type);
    renderList();
    return;
  }
  if (name === "detail") {
    $("#view-detail").classList.remove("hidden");
    renderDetail(opts.type, opts.index);
    return;
  }
}

function setActiveTab(tab) {
  state.currentTab = tab;
  for (const btn of $$(".tab")) {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  }
}

function capitalize(s) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
function renderDashboard() {
  if (!state.data) { showView("empty"); return; }
  const { loads, trips, fuel, fileName, loadedAt } = state.data;

  $("#meta-name").textContent = fileName || "—";
  $("#meta-loaded").textContent = new Date(loadedAt).toLocaleString();
  $("#meta-rows").textContent =
    `${fmtNum(loads.length)} loads · ${fmtNum(trips.length)} trips · ${fmtNum(fuel.length)} fuel`;

  // KPIs
  const totalRevenue = sum(loads, "Customer Revenue");
  const totalMargin = sum(loads, "Gross Margin");
  const totalMiles = sum(loads, "Total Dispatch Mileage") || sum(trips, "Total Miles");
  const fuelSpend = sum(fuel, "Net Total");

  const loadsThisWeek = loads.filter(
    (l) => isWithinDays(l["Scheduled Pickup"] || l["Created"], 7),
  ).length;
  const fuelThisWeek = sum(
    fuel.filter((f) => isWithinDays(f["Transaction Date"], 7)),
    "Net Total",
  );

  const marginPct = totalRevenue > 0 ? (totalMargin / totalRevenue) * 100 : 0;

  $("#kpi-grid").innerHTML = [
    kpi("Customer Revenue", fmtMoney(totalRevenue), `${fmtNum(loads.length)} loads`),
    kpi("Gross Margin", fmtMoney(totalMargin), `${marginPct.toFixed(1)}%`),
    kpi("Total Miles", fmtNum(Math.round(totalMiles))),
    kpi("Fuel Spend", fmtMoney(fuelSpend), `${fmtNum(fuel.length)} txns`),
    kpi("Loads This Week", fmtNum(loadsThisWeek)),
    kpi("Fuel This Week", fmtMoney(fuelThisWeek)),
  ].join("");

  // Recent loads (last 8 by Created or Scheduled Pickup)
  const recent = [...loads]
    .map((l, i) => ({ ...l, __i: i, __d: parsePipelineDate(l["Scheduled Pickup"] || l["Created"]) }))
    .sort((a, b) => (b.__d?.getTime() || 0) - (a.__d?.getTime() || 0))
    .slice(0, 8);
  $("#recent-loads").innerHTML = recent.map(loadRowHtml).join("") ||
    `<li><div class="row-main"><div class="row-sub">No recent loads.</div></div></li>`;
}

function kpi(label, value, sub = "") {
  return `<div class="kpi">
    <div class="label">${escapeHtml(label)}</div>
    <div class="value">${escapeHtml(value)}</div>
    ${sub ? `<div class="sub">${escapeHtml(sub)}</div>` : ""}
  </div>`;
}

function sum(rows, key) {
  let total = 0;
  for (const r of rows) {
    const v = Number(r?.[key]);
    if (isFinite(v)) total += v;
  }
  return total;
}

// ---------------------------------------------------------------------------
// Lists
// ---------------------------------------------------------------------------
function rowsFor(type) {
  if (!state.data) return [];
  return state.data[type] || [];
}

function statusKeyFor(type) {
  return type === "loads" ? "Load Status" :
         type === "trips" ? "Trip Status" :
         type === "fuel"  ? "Paid / Stubbed" : null;
}

function titleKeyFor(type) {
  return type === "loads" ? "Load #" :
         type === "trips" ? "Trip #" :
         type === "fuel"  ? "Transaction Id" : null;
}

function renderList() {
  const type = state.list.type;
  const all = rowsFor(type);
  const statusKey = statusKeyFor(type);

  // Populate status filter options on first render of this list
  const sel = $("#status-filter");
  sel.innerHTML = `<option value="">All ${type}</option>`;
  if (statusKey) {
    const seen = new Set();
    for (const r of all) {
      const s = r[statusKey];
      if (s && !seen.has(s)) { seen.add(s); }
    }
    for (const s of [...seen].sort()) {
      const opt = document.createElement("option");
      opt.value = String(s);
      opt.textContent = String(s);
      if (state.list.status === String(s)) opt.selected = true;
      sel.appendChild(opt);
    }
  }
  $("#search-input").value = state.list.search;

  // Filter
  const q = state.list.search.trim().toLowerCase();
  const status = state.list.status;
  const filtered = all.filter((r) => {
    if (status && statusKey && String(r[statusKey] ?? "") !== status) return false;
    if (!q) return true;
    return Object.values(r).some(
      (v) => v != null && String(v).toLowerCase().includes(q),
    );
  });

  const ul = $("#list-rows");
  $("#list-empty").classList.toggle("hidden", filtered.length !== 0);

  const builder = type === "loads" ? loadRowHtml :
                  type === "trips" ? tripRowHtml :
                  fuelRowHtml;

  // Keep original index so detail-view link still works after filtering
  const indexed = filtered.map((r) => ({ row: r, idx: all.indexOf(r) }));
  ul.innerHTML = indexed.slice(0, 300).map(({ row, idx }) =>
    builder({ ...row, __i: idx }),
  ).join("");

  if (filtered.length > 300) {
    ul.innerHTML += `<li><div class="row-main"><div class="row-sub">Showing first 300 of ${filtered.length} — refine your search to see more.</div></div></li>`;
  }
}

function loadRowHtml(r) {
  const id = r["Load #"] ?? "";
  const customer = r["Customer"] ?? "";
  const pick = `${r["Pick City"] ?? ""}${r["Pick State"] ? ", " + r["Pick State"] : ""}`;
  const drop = `${r["Drop City"] ?? ""}${r["Drop State"] ? ", " + r["Drop State"] : ""}`;
  const status = r["Load Status"] ?? "";
  const revenue = r["Customer Revenue"];
  return `<li data-type="loads" data-index="${r.__i ?? ""}">
    <div class="row-main">
      <div class="row-title">${escapeHtml(`#${id} · ${customer}`)}</div>
      <div class="row-sub">${escapeHtml(`${pick} → ${drop}`)}</div>
    </div>
    <div class="row-side">
      <strong>${escapeHtml(fmtMoney(revenue))}</strong>
      <span class="badge ${statusClass(status)}">${escapeHtml(status || "—")}</span>
    </div>
  </li>`;
}

function tripRowHtml(r) {
  const id = r["Trip #"] ?? "";
  const driver = r["Driver 1"] ?? "";
  const carrier = r["Carrier"] ?? "";
  const pick = `${r["Pick City"] ?? ""}${r["Pick State"] ? ", " + r["Pick State"] : ""}`;
  const drop = `${r["Drop City"] ?? ""}${r["Drop State"] ? ", " + r["Drop State"] : ""}`;
  const status = r["Trip Status"] ?? "";
  const value = r["Trip Value"];
  return `<li data-type="trips" data-index="${r.__i ?? ""}">
    <div class="row-main">
      <div class="row-title">${escapeHtml(`#${id} · ${driver || carrier}`)}</div>
      <div class="row-sub">${escapeHtml(`${pick} → ${drop}`)}</div>
    </div>
    <div class="row-side">
      <strong>${escapeHtml(fmtMoney(value))}</strong>
      <span class="badge ${statusClass(status)}">${escapeHtml(status || "—")}</span>
    </div>
  </li>`;
}

function fuelRowHtml(r) {
  const driver = r["Driver"] ?? "";
  const truck = r["Truck"] ?? "";
  const loc = `${r["Location Name"] ?? ""}${r["City"] ? " · " + r["City"] : ""}${r["State"] ? ", " + r["State"] : ""}`;
  const total = r["Net Total"];
  const date = r["Transaction Date"] ?? "";
  return `<li data-type="fuel" data-index="${r.__i ?? ""}">
    <div class="row-main">
      <div class="row-title">${escapeHtml(`${driver || "—"} · Truck ${truck || "?"}`)}</div>
      <div class="row-sub">${escapeHtml(loc || "Location unknown")}</div>
    </div>
    <div class="row-side">
      <strong>${escapeHtml(fmtMoney(total))}</strong>
      <span>${escapeHtml(fmtDate(date))}</span>
    </div>
  </li>`;
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------
function renderDetail(type, index) {
  const row = rowsFor(type)[index];
  if (!row) {
    $("#detail-title").textContent = "Not found";
    $("#detail-body").innerHTML = "";
    return;
  }
  const titleKey = titleKeyFor(type);
  $("#detail-title").textContent =
    `${capitalize(type).slice(0, -1)} ${row[titleKey] ?? ""}`.trim();

  const entries = Object.entries(row).filter(([, v]) => v !== null && v !== "" && v !== undefined);
  $("#detail-body").innerHTML = entries.map(([k, v]) => {
    let display = v;
    if (typeof v === "number") {
      if (/rate|revenue|amount|charge|margin|pay|cost|fee|total|fuel|advances|detention|lumper|accessor/i.test(k)) {
        display = fmtMoneyFull(v);
      } else if (/mile/i.test(k)) {
        display = `${fmtNum(Math.round(v))} mi`;
      } else {
        display = fmtNum(v);
      }
    }
    return `<div class="row">
      <span class="k">${escapeHtml(k)}</span>
      <span class="v">${escapeHtml(String(display))}</span>
    </div>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
function renderSettings() {
  $("#default-url").value = localStorage.getItem(URL_PREF_KEY) || "";
  $("#set-meta-name").textContent = state.data?.fileName || "—";
  $("#set-meta-loaded").textContent = state.data
    ? new Date(state.data.loadedAt).toLocaleString() : "—";
  $("#app-version").textContent = APP_VERSION;
}

// ---------------------------------------------------------------------------
// Data loading flows
// ---------------------------------------------------------------------------
async function handleFile(file) {
  if (!file) return;
  showLoading("Parsing spreadsheet…");
  try {
    const buf = await file.arrayBuffer();
    const data = await parseXlsx(buf, file.name);
    await saveData(data);
    state.data = data;
    showView("dashboard");
  } catch (e) {
    alert(`Could not parse file: ${e.message}`);
  } finally {
    hideLoading();
  }
}

async function loadFromUrl(url) {
  showLoading(`Downloading ${shortenUrl(url)}…`);
  try {
    const resp = await fetch(url, { mode: "cors" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const buf = await resp.arrayBuffer();
    const name = url.split("/").pop().split("?")[0] || "Alvys_Master.xlsx";
    const data = await parseXlsx(buf, name);
    await saveData(data);
    state.data = data;
    showView("dashboard");
  } catch (e) {
    alert(`Could not load URL: ${e.message}\n\nIf this is a OneDrive share link, make sure it's a direct download link (ends in &download=1 for share links, or use a SharePoint direct link).`);
  } finally {
    hideLoading();
  }
}

function shortenUrl(u) {
  try {
    const url = new URL(u);
    return url.hostname + (url.pathname.length > 30 ? url.pathname.slice(0, 30) + "…" : url.pathname);
  } catch { return u; }
}

function showLoading(msg) {
  $("#loading-msg").textContent = msg || "Loading…";
  $("#loading").classList.remove("hidden");
}
function hideLoading() { $("#loading").classList.add("hidden"); }

// ---------------------------------------------------------------------------
// Misc helpers
// ---------------------------------------------------------------------------
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------
function wireEvents() {
  $("#file-input").addEventListener("change", (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    handleFile(f);
  });

  $("#url-btn").addEventListener("click", () => {
    $("#url-input").value = localStorage.getItem(URL_PREF_KEY) || "";
    $("#url-dialog").showModal();
  });

  $("#url-form").addEventListener("submit", (e) => {
    if (e.submitter && e.submitter.value === "ok") {
      const u = $("#url-input").value.trim();
      if (u) loadFromUrl(u);
    }
  });

  $("#refresh-btn").addEventListener("click", () => {
    const u = localStorage.getItem(URL_PREF_KEY);
    if (u) {
      loadFromUrl(u);
    } else {
      $("#file-input").click();
    }
  });

  for (const btn of $$(".tab")) {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      if (!state.data && tab !== "settings") {
        showView("empty"); setActiveTab(tab);
        return;
      }
      if (tab === "dashboard") return showView("dashboard");
      if (tab === "settings") return showView("settings");
      // tabs that map to a list view
      state.list.type = tab;
      state.list.search = "";
      state.list.status = "";
      showView("list", { type: tab });
    });
  }

  $("#list-rows").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-type]");
    if (!li) return;
    showView("detail", { type: li.dataset.type, index: Number(li.dataset.index) });
  });

  $("#recent-loads").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-type]");
    if (!li) return;
    showView("detail", { type: li.dataset.type, index: Number(li.dataset.index) });
  });

  $("#back-btn").addEventListener("click", () => {
    if (state.list.type) showView("list");
    else showView("dashboard");
  });

  $("#search-input").addEventListener("input", (e) => {
    state.list.search = e.target.value;
    renderList();
  });
  $("#status-filter").addEventListener("change", (e) => {
    state.list.status = e.target.value;
    renderList();
  });

  $("#save-url").addEventListener("click", () => {
    const v = $("#default-url").value.trim();
    if (v) localStorage.setItem(URL_PREF_KEY, v);
    else localStorage.removeItem(URL_PREF_KEY);
    flash("Saved");
  });

  $("#clear-data").addEventListener("click", async () => {
    if (!confirm("Remove cached pipeline data from this device?")) return;
    await clearData();
    state.data = null;
    showView("empty");
  });
}

function flash(msg) {
  // Quick inline notification — reuses the loader styling for a brief moment.
  showLoading(msg);
  setTimeout(hideLoading, 700);
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function boot() {
  wireEvents();

  // Register service worker for offline support
  if ("serviceWorker" in navigator) {
    try {
      await navigator.serviceWorker.register("service-worker.js");
    } catch (e) {
      console.warn("SW registration failed:", e);
    }
  }

  // Hydrate from IndexedDB
  try {
    const cached = await loadData();
    if (cached) {
      state.data = cached;
      showView("dashboard");
      return;
    }
  } catch (e) {
    console.warn("DB load failed:", e);
  }

  showView("empty");
}

boot();
