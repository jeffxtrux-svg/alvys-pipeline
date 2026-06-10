"""
Alvys Master Fixer — desktop GUI tool (hybrid API + manual merge).

Strategy:
  • API pipeline (GitHub Actions) runs 3×/day → "Alvys Pipeline.xlsx"
    on OneDrive.  Has all load/trip/fuel fields + X-Linx carrier rates.
  • Gap: X-Trux Driver Rate.  API gives current rate × miles, not the
    actual settled amount.
  • This tool downloads the API file, overlays the accurate X-Trux
    Driver Rate from your manual TMS exports (joined on Load #), and
    uploads the result as "Alvys Master 2026.xlsx" for Power BI.

Accepts the manual export as ONE combined workbook OR as two separate
files — one for Loads (e.g. Export 4) and one for Trips (e.g. Export 5).

Run:
    python -m src.master_fixer_gui
    or double-click "Alvys Master Fixer.command" on the Desktop.
"""
from __future__ import annotations

import io
import logging
import os
import threading
from pathlib import Path

import pandas as pd

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND = True
except ImportError:
    _DND = False

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except Exception:
    pass

log = logging.getLogger("master_fixer_gui")

# ── palette ──────────────────────────────────────────────────────────────────
BG       = "#1e1e2e"
PANEL    = "#2a2a3e"
CARD     = "#32324a"
ACCENT   = "#7c6af7"
ACCHOV   = "#9d8fff"
SUCCESS  = "#50fa7b"
WARNING  = "#f1fa8c"
ERROR    = "#ff5555"
TEXT     = "#f8f8f2"
MUTED    = "#888899"
BORDER   = "#44475a"
READY_BD = "#50fa7b"


# ── helpers ───────────────────────────────────────────────────────────────────

def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cl = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in df.columns:
            return c
        if c.lower() in cl:
            return cl[c.lower()]
    return None


def _norm_id(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lstrip("0").str.replace(r"\s+", "", regex=True)


def _read_sheets(src: str | Path | bytes) -> dict[str, pd.DataFrame]:
    if isinstance(src, bytes):
        src = io.BytesIO(src)
        return pd.read_excel(src, sheet_name=None, engine="openpyxl")
    path = Path(src)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        return {path.stem: df}
    return pd.read_excel(path, sheet_name=None, engine="openpyxl")


def _has_data(df: pd.DataFrame) -> bool:
    return _find_col(df, ["Customer Revenue", "Revenue", "Load #",
                          "LoadNumber", "Trip #", "TripNumber"]) is not None


def _first_data_sheet(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    """Return the first sheet that looks like load/trip data."""
    for df in sheets.values():
        if _has_data(df):
            return df
    return next(iter(sheets.values()), None) if sheets else None


def _build_manual_dict(
    loads_sheets: dict[str, pd.DataFrame] | None,
    trips_sheets: dict[str, pd.DataFrame] | None,
) -> dict[str, pd.DataFrame]:
    """
    Combine the (possibly separate) manual Loads and Trips exports into a
    single dict keyed by "Loads" / "Trips" so process_and_upload can find them.

    If only one file is given and it already contains both sheets, it's used
    as-is.  If both files are given, the first data sheet of each is used.
    """
    result: dict[str, pd.DataFrame] = {}

    # Case: only one file provided that contains both sheets
    if loads_sheets and not trips_sheets:
        has_loads = any(k.lower() in ("loads", "load") for k in loads_sheets)
        has_trips = any(k.lower() in ("trips", "trip") for k in loads_sheets)
        if has_loads and has_trips:
            return loads_sheets          # already a combined workbook
        # Single-sheet export — treat it as Loads
        df = _first_data_sheet(loads_sheets)
        if df is not None:
            result["Loads"] = df
        return result

    # Case: two separate files
    if loads_sheets:
        # Prefer a sheet literally named "Loads"; fall back to first data sheet
        df = (loads_sheets.get("Loads") or loads_sheets.get("loads")
              or _first_data_sheet(loads_sheets))
        if df is not None:
            result["Loads"] = df

    if trips_sheets:
        df = (trips_sheets.get("Trips") or trips_sheets.get("trips")
              or _first_data_sheet(trips_sheets))
        if df is not None:
            result["Trips"] = df

    return result


# ── core merge logic ──────────────────────────────────────────────────────────

def _overlay_driver_rate(
    api_df: pd.DataFrame,
    manual_df: pd.DataFrame,
    label: str,
    log_fn,
) -> tuple[pd.DataFrame, int, int]:
    """Join manual Driver Rate onto API data by Load #.
    Returns (patched_df, n_patched, n_api_only)."""

    id_cands  = ["Load #", "Load Number", "LoadNumber", "Trip #",
                 "TripNumber", "Load_Number"]
    dr_cands  = ["Driver Rate", "DriverRate"]
    rev_cands = ["Customer Revenue", "Revenue"]
    gm_cands  = ["Gross Margin", "GrossMargin", "Margin"]

    api_id  = _find_col(api_df,    id_cands)
    man_id  = _find_col(manual_df, id_cands)
    api_dr  = _find_col(api_df,    dr_cands)
    man_dr  = _find_col(manual_df, dr_cands)
    api_rev = _find_col(api_df,    rev_cands)
    api_gm  = _find_col(api_df,    gm_cands)

    if not api_id or not man_id:
        log_fn(f"⚠  {label}: no Load # column found — skipping overlay.")
        return api_df, 0, 0
    if not api_dr or not man_dr:
        log_fn(f"⚠  {label}: no Driver Rate column found — skipping overlay.")
        return api_df, 0, 0

    # Build lookup: normalised key → manual Driver Rate (non-zero only)
    lookup = (
        manual_df[[man_id, man_dr]].copy()
        .assign(_k=lambda d: _norm_id(d[man_id]),
                _dr=lambda d: pd.to_numeric(d[man_dr], errors="coerce").fillna(0))
        .query("_dr > 0")
        .drop_duplicates("_k")
        .set_index("_k")["_dr"]
    )
    log_fn(f"  {label} manual: {len(lookup):,} rows with Driver Rate > 0")

    out = api_df.copy()
    out.loc[:, "_k"]    = _norm_id(out[api_id])
    out.loc[:, "_a_dr"] = pd.to_numeric(out[api_dr], errors="coerce").fillna(0)
    out.loc[:, "_m_dr"] = out["_k"].map(lookup).fillna(0)

    mask       = out["_m_dr"] > 0
    n_patched  = int(mask.sum())
    n_api_only = int((~mask).sum())

    out.loc[:, api_dr] = out["_m_dr"].where(mask, out["_a_dr"])

    if api_gm and api_rev:
        rev = pd.to_numeric(out[api_rev], errors="coerce").fillna(0)
        dr  = pd.to_numeric(out[api_dr],  errors="coerce").fillna(0)
        out.loc[:, api_gm] = rev - dr

    out.drop(columns=["_k", "_a_dr", "_m_dr"], inplace=True)
    return out, n_patched, n_api_only


def _get_creds() -> dict | None:
    c = {k: os.environ.get(v, "") for k, v in {
        "tenant": "AZURE_TENANT_ID",
        "client": "AZURE_CLIENT_ID",
        "secret": "AZURE_CLIENT_SECRET",
        "upn":    "ONEDRIVE_USER_UPN",
        "folder": "ONEDRIVE_FOLDER_PATH",
    }.items()}
    return None if any(not c[k] for k in ("tenant", "client", "secret", "upn")) else c


def process_and_upload(
    api_sheets:    dict[str, pd.DataFrame],
    manual_sheets: dict[str, pd.DataFrame],
    target_name:   str,
    upload:        bool,
    save_path:     str | None,
    log_fn,
) -> bool:
    try:
        def _find(sheets, prefer):
            for p in prefer:
                for k, df in sheets.items():
                    if k.lower() == p.lower():
                        return k, df
            for k, df in sheets.items():
                if _has_data(df):
                    return k, df
            return None, None

        api_ln, api_loads = _find(api_sheets,    ["Loads", "Load"])
        api_tn, api_trips = _find(api_sheets,    ["Trips", "Trip"])
        man_ln, man_loads = _find(manual_sheets, ["Loads", "Load"])
        man_tn, man_trips = _find(manual_sheets, ["Trips", "Trip"])

        if api_loads is None:
            log_fn("✗ No Loads sheet found in API data.")
            return False

        log_fn(f"API Loads  : '{api_ln}'  {len(api_loads):,} rows")
        if api_trips  is not None: log_fn(f"API Trips  : '{api_tn}'  {len(api_trips):,} rows")
        if man_loads  is not None: log_fn(f"Manual Loads: '{man_ln}'  {len(man_loads):,} rows")
        if man_trips  is not None: log_fn(f"Manual Trips: '{man_tn}'  {len(man_trips):,} rows")

        log_fn("\nOverlaying Driver Rate …")
        n_loads = n_trips = 0

        if man_loads is not None:
            api_loads, n_loads, n_load_api = _overlay_driver_rate(
                api_loads, man_loads, "Loads", log_fn)
            log_fn(f"  Loads: {n_loads:,} patched from manual, {n_load_api:,} kept from API")
        else:
            log_fn("  ⚠  No manual Loads — Driver Rate unchanged (API only)")

        if api_trips is not None:
            if man_trips is not None:
                api_trips, n_trips, n_trip_api = _overlay_driver_rate(
                    api_trips, man_trips, "Trips", log_fn)
                log_fn(f"  Trips: {n_trips:,} patched from manual, {n_trip_api:,} kept from API")
            else:
                log_fn("  ℹ  No manual Trips file — Trips Driver Rate unchanged")

        if n_loads == 0 and n_trips == 0:
            log_fn("⚠  Zero rows patched — check that Load # values match "
                   "between API and manual files.")

        log_fn("\nBuilding workbook …")
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            api_loads.to_excel(writer, sheet_name="Loads", index=False)
            if api_trips is not None:
                api_trips.to_excel(writer, sheet_name="Trips", index=False)
            for name, df in api_sheets.items():
                if name not in (api_ln, api_tn):
                    df.to_excel(writer, sheet_name=name, index=False)
        buf.seek(0)

        if upload:
            log_fn("\nConnecting to OneDrive …")
            creds = _get_creds()
            if not creds:
                log_fn("✗ Missing Azure / OneDrive credentials in .env")
                return False
            from src.onedrive_upload import get_token, ensure_folder, upload_file
            token = get_token(creds["tenant"], creds["client"], creds["secret"])
            log_fn("  Token OK")
            if creds["folder"]:
                ensure_folder(token, creds["upn"], creds["folder"])
            tmp = Path("/tmp") / target_name
            tmp.write_bytes(buf.getvalue())
            upload_file(token, creds["upn"], creds["folder"], target_name, tmp)
            tmp.unlink(missing_ok=True)
            log_fn(f"✓ Uploaded: {target_name}")
        else:
            out = Path(save_path) if save_path else Path.home() / "Downloads" / target_name
            out.write_bytes(buf.getvalue())
            log_fn(f"✓ Saved: {out}")

        return True

    except Exception as exc:
        log_fn(f"✗ {exc}")
        log.exception("process_and_upload failed")
        return False


# ── FileZone widget ───────────────────────────────────────────────────────────

class FileZone(tk.Frame):
    """Small file-picker zone: browse button + optional DnD + status line."""

    def __init__(self, master, title: str, hint: str,
                 optional: bool = False,
                 show_download: bool = False,
                 accept_dnd: bool = False, **kw):
        super().__init__(master, bg=CARD, bd=0,
                         highlightthickness=1, highlightbackground=BORDER, **kw)
        self._sheets: dict[str, pd.DataFrame] | None = None
        self._optional = optional

        hdr = tk.Frame(self, bg=CARD)
        hdr.pack(fill="x", padx=12, pady=(12, 0))
        tk.Label(hdr, text=title, font=("SF Pro", 12, "bold"),
                 bg=CARD, fg=TEXT).pack(side="left")
        if optional:
            tk.Label(hdr, text=" optional", font=("SF Pro", 10),
                     bg=CARD, fg=MUTED).pack(side="left")

        tk.Label(self, text=hint, font=("SF Pro", 10),
                 bg=CARD, fg=MUTED).pack(anchor="w", padx=12, pady=(2, 8))

        btn_row = tk.Frame(self, bg=CARD)
        btn_row.pack(fill="x", padx=12, pady=(0, 6))

        if show_download:
            self._dl_btn = tk.Button(
                btn_row, text="⬇  Download from OneDrive",
                font=("SF Pro", 10), bg=ACCENT, fg="white",
                activebackground=ACCHOV, relief="flat",
                padx=8, pady=5, cursor="hand2",
                command=self._download,
            )
            self._dl_btn.pack(side="left", padx=(0, 6))

        tk.Button(
            btn_row,
            text="Browse…" if show_download else "📂  Browse",
            font=("SF Pro", 10), bg=PANEL, fg=TEXT,
            activebackground=BORDER, relief="flat",
            padx=8, pady=5, cursor="hand2",
            highlightthickness=1, highlightbackground=BORDER,
            command=self._browse,
        ).pack(side="left")

        if accept_dnd:
            tk.Label(self, text="or drag here",
                     font=("SF Pro", 9), bg=CARD, fg=MUTED).pack()

        self._status = tk.Label(self, text="No file" if not optional else "—",
                                font=("SF Pro", 10), bg=CARD, fg=MUTED,
                                wraplength=240, justify="left")
        self._status.pack(anchor="w", padx=12, pady=(2, 12))

        if accept_dnd:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Excel / CSV files", "*.xlsx *.xls *.csv"),
                       ("Excel files", "*.xlsx *.xls"),
                       ("CSV files", "*.csv"),
                       ("All files", "*.*")])
        if p:
            self._load(p)

    def _on_drop(self, event):
        raw = event.data.strip()
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        self._load(raw.split("} {")[0] if "} {" in raw else raw)

    def _load(self, path: str):
        self._set_status("⏳ Loading …", MUTED)
        def worker():
            try:
                sheets = _read_sheets(path)
                self._sheets = sheets
                names = list(sheets.keys())
                total = sum(len(df) for df in sheets.values())
                dr_count = 0
                for df in sheets.values():
                    dr_col = _find_col(df, ["Driver Rate", "DriverRate"])
                    if dr_col:
                        dr_count = int(
                            (pd.to_numeric(df[dr_col], errors="coerce").fillna(0) > 0).sum())
                        break
                desc = f"✓ {Path(path).name}"
                if len(names) > 1:
                    desc += f"  [{', '.join(names)}]"
                desc += f"\n{total:,} rows"
                if dr_count:
                    desc += f"  ·  {dr_count:,} with Driver Rate"
                self.after(0, self._set_status, desc, SUCCESS)
                self.after(0, self.event_generate, "<<FileLoaded>>")
            except Exception as e:
                self.after(0, self._set_status, f"✗ {e}", ERROR)
        threading.Thread(target=worker, daemon=True).start()

    def _download(self):
        creds = _get_creds()
        if not creds:
            messagebox.showerror("Missing credentials",
                                 "Set Azure / OneDrive credentials in .env")
            return
        self._set_status("⏳ Downloading …", MUTED)
        if hasattr(self, "_dl_btn"):
            self._dl_btn.config(state="disabled")
        def worker():
            try:
                from src.onedrive_upload import get_token, download_file
                token = get_token(creds["tenant"], creds["client"], creds["secret"])
                folder = creds["folder"]
                fname  = "Alvys Pipeline.xlsx"
                fpath  = f"{folder}/{fname}" if folder else fname
                raw    = download_file(token, creds["upn"], fpath)
                sheets = _read_sheets(raw)
                self._sheets = sheets
                names  = list(sheets.keys())
                total  = sum(len(df) for df in sheets.values())
                desc   = (f"✓ {fname} (OneDrive)\n"
                          f"[{', '.join(names)}]  {total:,} rows")
                self.after(0, self._set_status, desc, SUCCESS)
                self.after(0, self.event_generate, "<<FileLoaded>>")
            except Exception as e:
                self.after(0, self._set_status, f"✗ {e}", ERROR)
            finally:
                if hasattr(self, "_dl_btn"):
                    self.after(0, self._dl_btn.config, {"state": "normal"})
        threading.Thread(target=worker, daemon=True).start()

    def _set_status(self, msg: str, colour: str):
        self._status.config(text=msg, fg=colour)
        bd = READY_BD if colour == SUCCESS else BORDER
        self.config(highlightbackground=bd)

    @property
    def sheets(self) -> dict[str, pd.DataFrame] | None:
        return self._sheets

    def reset(self):
        self._sheets = None
        self._set_status("No file" if not self._optional else "—", MUTED)
        self.config(highlightbackground=BORDER)


# ── Main window ───────────────────────────────────────────────────────────────

class App(tk.Tk if not _DND else TkinterDnD.Tk):   # type: ignore[misc]

    def __init__(self):
        super().__init__()
        self.title("Alvys Master Fixer")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._build()
        self._centre()

    def _centre(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build(self):
        # ── header ────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Alvys Master Fixer",
                 font=("SF Pro", 17, "bold"), bg=PANEL, fg=TEXT,
                 pady=14).pack(side="left", padx=20)
        tk.Label(hdr,
                 text="API data  +  manual Driver Rate  →  OneDrive master",
                 font=("SF Pro", 11), bg=PANEL, fg=MUTED).pack(side="left")

        # ── three-column zone row ─────────────────────────────────────────
        cols = tk.Frame(self, bg=BG)
        cols.pack(padx=16, pady=16, fill="x")

        # Left: API data
        self._api_zone = FileZone(
            cols,
            title="① API Data",
            hint="Download latest API run\nor browse for file.",
            show_download=True,
            accept_dnd=_DND,
        )
        self._api_zone.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._api_zone.bind("<<FileLoaded>>", self._on_change)

        # Middle: Manual Loads
        self._man_loads_zone = FileZone(
            cols,
            title="② Manual Loads",
            hint="Export 4 (or your Loads\nexport from Alvys TMS).",
            accept_dnd=_DND,
        )
        self._man_loads_zone.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._man_loads_zone.bind("<<FileLoaded>>", self._on_change)

        # Right: Manual Trips
        self._man_trips_zone = FileZone(
            cols,
            title="③ Manual Trips",
            hint="Export 5 (or your Trips\nexport from Alvys TMS).",
            optional=True,
            accept_dnd=_DND,
        )
        self._man_trips_zone.pack(side="left", fill="both", expand=True)
        self._man_trips_zone.bind("<<FileLoaded>>", self._on_change)

        if not _DND:
            tk.Label(self, text="💡 pip install tkinterdnd2  for drag-and-drop",
                     font=("SF Pro", 10), bg=BG, fg=MUTED).pack()

        # ── summary ───────────────────────────────────────────────────────
        self._summary = tk.Label(
            self,
            text="Load API data + at least the Loads export to begin.",
            font=("SF Pro", 11), bg=BG, fg=MUTED,
            wraplength=680, justify="left",
        )
        self._summary.pack(anchor="w", padx=20, pady=(0, 4))

        # ── options ───────────────────────────────────────────────────────
        opts = tk.Frame(self, bg=BG)
        opts.pack(padx=20, fill="x")
        tk.Label(opts, text="Output filename:",
                 font=("SF Pro", 11), bg=BG, fg=TEXT).pack(side="left")
        self._name_var = tk.StringVar(value="Alvys Master 2026.xlsx")
        tk.Entry(opts, textvariable=self._name_var,
                 font=("SF Pro", 11), bg=PANEL, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 width=32).pack(side="left", padx=(8, 0), ipady=4)

        # ── buttons ───────────────────────────────────────────────────────
        btns = tk.Frame(self, bg=BG)
        btns.pack(padx=20, pady=14, fill="x")

        self._upload_btn = tk.Button(
            btns, text="⬆  Merge & Upload to OneDrive",
            font=("SF Pro", 13, "bold"),
            bg=ACCENT, fg="white", activebackground=ACCHOV,
            relief="flat", bd=0, padx=16, pady=10, cursor="hand2",
            state="disabled",
            command=lambda: self._run(upload=True),
        )
        self._upload_btn.pack(side="left", padx=(0, 10))

        self._save_btn = tk.Button(
            btns, text="💾  Merge & Save Locally",
            font=("SF Pro", 12),
            bg=PANEL, fg=TEXT, activebackground=BORDER,
            relief="flat", bd=0, padx=16, pady=10, cursor="hand2",
            highlightthickness=1, highlightbackground=BORDER,
            state="disabled",
            command=lambda: self._run(upload=False),
        )
        self._save_btn.pack(side="left")

        tk.Button(
            btns, text="↺  Reset",
            font=("SF Pro", 11), bg=PANEL, fg=MUTED,
            activebackground=BORDER, relief="flat", bd=0,
            padx=10, pady=10, cursor="hand2",
            command=self._reset,
        ).pack(side="right")

        # ── log ───────────────────────────────────────────────────────────
        lf = tk.Frame(self, bg=BG)
        lf.pack(padx=20, pady=(0, 18), fill="both")
        self._log = tk.Text(
            lf, height=9, bg=PANEL, fg=TEXT,
            font=("SF Mono", 11), relief="flat",
            highlightthickness=1, highlightbackground=BORDER,
            state="disabled", wrap="word",
        )
        sb = ttk.Scrollbar(lf, command=self._log.yview)
        self._log.config(yscrollcommand=sb.set)
        self._log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._log.tag_config("ok",   foreground=SUCCESS)
        self._log.tag_config("warn", foreground=WARNING)
        self._log.tag_config("err",  foreground=ERROR)
        self._log.tag_config("info", foreground=TEXT)
        self._emit("Ready — load the files above to begin.", "info")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _on_change(self, _=None):
        api   = self._api_zone.sheets
        loads = self._man_loads_zone.sheets
        trips = self._man_trips_zone.sheets
        ready = bool(api and loads)
        state = "normal" if ready else "disabled"
        self._upload_btn.config(state=state)
        self._save_btn.config(state=state)
        self._update_summary(api, loads, trips)

    def _update_summary(self, api, loads, trips):
        if not api and not loads:
            self._summary.config(
                text="Load API data + at least the Loads export to begin.", fg=MUTED)
            return
        if api and not loads:
            self._summary.config(
                text="✓ API data loaded.  Now add the Manual Loads export (②).", fg=WARNING)
            return

        parts = []
        if api:
            api_total = sum(len(df) for df in api.values())
            parts.append(f"API: {api_total:,} rows")
        if loads:
            df = _first_data_sheet(loads)
            if df is not None:
                dr_col = _find_col(df, ["Driver Rate", "DriverRate"])
                n_dr = int((pd.to_numeric(df[dr_col], errors="coerce").fillna(0) > 0).sum()) \
                       if dr_col else 0
                parts.append(f"Loads manual: {len(df):,} rows, {n_dr:,} with DR")
        if trips:
            df = _first_data_sheet(trips)
            if df is not None:
                parts.append(f"Trips manual: {len(df):,} rows")
        else:
            parts.append("Trips: API only")

        self._summary.config(
            text="✓ Ready.  " + "  ·  ".join(parts), fg=SUCCESS)

    def _emit(self, msg: str, tag: str = "info"):
        if msg.startswith("✓"):   tag = "ok"
        elif msg.startswith("⚠"): tag = "warn"
        elif msg.startswith("✗"): tag = "err"
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n", tag)
        self._log.see("end")
        self._log.config(state="disabled")

    def _set_busy(self, busy: bool):
        s = "disabled" if busy else "normal"
        self._upload_btn.config(state=s,
            text="⏳  Working …" if busy else "⬆  Merge & Upload to OneDrive")
        self._save_btn.config(state=s)

    def _run(self, upload: bool):
        api   = self._api_zone.sheets
        loads = self._man_loads_zone.sheets
        trips = self._man_trips_zone.sheets
        name  = self._name_var.get().strip() or "Alvys Master 2026.xlsx"

        if not api or not loads:
            messagebox.showwarning("Not ready", "Load API data and Loads export first.")
            return

        save_path = None
        if not upload:
            save_path = filedialog.asksaveasfilename(
                initialfile=name, defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")])
            if not save_path:
                return

        manual = _build_manual_dict(loads, trips)

        self._set_busy(True)
        self._emit("─" * 50, "info")

        def worker():
            ok = process_and_upload(
                api_sheets=api,
                manual_sheets=manual,
                target_name=name,
                upload=upload,
                save_path=save_path,
                log_fn=lambda m: self.after(0, self._emit, m),
            )
            def done():
                self._set_busy(False)
                if ok:
                    dest = "OneDrive" if upload else save_path
                    messagebox.showinfo("Done", f"✓ {name}\n→ {dest}")
            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _reset(self):
        self._api_zone.reset()
        self._man_loads_zone.reset()
        self._man_trips_zone.reset()
        self._on_change()
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")
        self._emit("Ready — load the files above to begin.", "info")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
