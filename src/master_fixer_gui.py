"""
Alvys Master Fixer — desktop GUI tool (hybrid API + manual merge).

Strategy:
  • API pipeline (GitHub Actions) already runs 3×/day and uploads
    "Alvys Pipeline.xlsx" to OneDrive — it has everything the Alvys API
    provides: all load/trip/fuel fields, X-Linx carrier rates, mileage, dates.
  • The one gap the API can't fill is X-Trux Driver Rate — the API only
    returns the driver's *current* per-mile rate, not the amount locked at
    settlement time.
  • This tool downloads the API data from OneDrive, overlays the accurate
    X-Trux Driver Rate from your manual TMS export (joined on Load #),
    and uploads the merged result as "Alvys Master 2026.xlsx" — the file
    Power BI and the scorecard email both read.

Run:
    python -m src.master_fixer_gui
    or double-click "Alvys Master Fixer.command" on the Desktop.
"""
from __future__ import annotations

import io
import logging
import os
import sys
import threading
from pathlib import Path

import pandas as pd

# ── optional drag-and-drop ───────────────────────────────────────────────────
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
READY    = "#1e3a2e"
READY_BD = "#50fa7b"


# ── helpers ──────────────────────────────────────────────────────────────────

def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cl = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in df.columns:
            return c
        if c.lower() in cl:
            return cl[c.lower()]
    return None


def _norm_load_num(s: pd.Series) -> pd.Series:
    """Normalise Load # to plain string for joining."""
    return s.astype(str).str.strip().str.lstrip("0").str.replace(r"\s+", "", regex=True)


def _best_data_sheet(xl: pd.ExcelFile, prefer: list[str] | None = None) -> str:
    """Return the sheet name that looks most like a Loads/Trips data sheet."""
    if prefer:
        for name in xl.sheet_names:
            if name.lower() in [p.lower() for p in prefer]:
                return name
    for name in xl.sheet_names:
        df = xl.parse(name, nrows=5)
        if _find_col(df, ["Customer Revenue", "Revenue", "CustomerRevenue"]):
            return name
    return xl.sheet_names[0]


def _read_all_sheets(path: str | Path | bytes) -> dict[str, pd.DataFrame]:
    """Read all sheets from an Excel file (path or bytes)."""
    if isinstance(path, bytes):
        src = io.BytesIO(path)
    else:
        src = path
    return pd.read_excel(src, sheet_name=None, engine="openpyxl")


# ── core merge logic ─────────────────────────────────────────────────────────

def _overlay_driver_rate(
    api_df: pd.DataFrame,
    manual_df: pd.DataFrame,
    log_fn,
) -> tuple[pd.DataFrame, int, int]:
    """
    Overlay manual Driver Rate onto API data, joined on Load #.

    For each row in api_df:
      - If manual export has Driver Rate > 0 for that Load #, use it.
      - Otherwise keep the API Driver Rate (which already has Carrier Rate
        as a fallback for X-Linx brokered loads).

    Returns (patched_df, n_xtrux_patched, n_xlinx_kept).
    """
    dr_cands  = ["Driver Rate",     "DriverRate"]
    cr_cands  = ["Carrier Rate",    "CarrierRate"]
    rev_cands = ["Customer Revenue","Revenue"]
    gm_cands  = ["Gross Margin",    "GrossMargin", "Margin"]
    id_cands  = ["Load #", "Load Number", "LoadNumber", "Load_Number"]

    # Identify columns
    api_id  = _find_col(api_df,    id_cands)
    man_id  = _find_col(manual_df, id_cands)
    api_dr  = _find_col(api_df,    dr_cands)
    man_dr  = _find_col(manual_df, dr_cands)
    api_rev = _find_col(api_df,    rev_cands)
    api_gm  = _find_col(api_df,    gm_cands)

    if not api_id or not man_id:
        log_fn("⚠  Could not find Load # column — skipping Driver Rate overlay.")
        return api_df, 0, 0
    if not api_dr or not man_dr:
        log_fn("⚠  Could not find Driver Rate column — skipping overlay.")
        return api_df, 0, 0

    out = api_df.copy()

    # Build lookup: normalised Load # → manual Driver Rate
    manual_lookup = (
        manual_df[[man_id, man_dr]].copy()
        .assign(_key=lambda d: _norm_load_num(d[man_id]),
                _manual_dr=lambda d: pd.to_numeric(d[man_dr], errors="coerce").fillna(0))
        .dropna(subset=["_manual_dr"])
        .query("_manual_dr > 0")
        .drop_duplicates("_key")
        .set_index("_key")["_manual_dr"]
    )
    log_fn(f"  Manual export: {len(manual_lookup):,} loads with Driver Rate > 0")

    out["_key"]       = _norm_load_num(out[api_id])
    out["_api_dr"]    = pd.to_numeric(out[api_dr],  errors="coerce").fillna(0)
    out["_manual_dr"] = out["_key"].map(manual_lookup).fillna(0)

    # Apply overlay: use manual DR where it exists
    patch_mask = out["_manual_dr"] > 0
    n_patched  = int(patch_mask.sum())
    n_api_only = int((~patch_mask).sum())

    out[api_dr] = out["_manual_dr"].where(patch_mask, out["_api_dr"])

    # Recompute Gross Margin
    if api_gm and api_rev:
        rev = pd.to_numeric(out[api_rev], errors="coerce").fillna(0)
        dr  = pd.to_numeric(out[api_dr],  errors="coerce").fillna(0)
        out[api_gm] = rev - dr
        log_fn(f"  Recomputed Gross Margin = Customer Revenue − Driver Rate")

    out.drop(columns=["_key", "_api_dr", "_manual_dr"], inplace=True)
    return out, n_patched, n_api_only


def _get_credentials() -> dict | None:
    creds = {
        "tenant":   os.environ.get("AZURE_TENANT_ID",     ""),
        "client":   os.environ.get("AZURE_CLIENT_ID",     ""),
        "secret":   os.environ.get("AZURE_CLIENT_SECRET", ""),
        "upn":      os.environ.get("ONEDRIVE_USER_UPN",   ""),
        "folder":   os.environ.get("ONEDRIVE_FOLDER_PATH", ""),
    }
    missing = [k for k, v in creds.items() if k != "folder" and not v]
    return None if missing else creds


def process_and_upload(
    api_data:      dict[str, pd.DataFrame],  # sheets from API file
    manual_data:   dict[str, pd.DataFrame],  # sheets from manual export
    target_name:   str,
    upload:        bool,
    save_path:     str | None,
    log_fn,
) -> bool:
    try:
        # ── Find the Loads & Trips sheets from each source ────────────────
        def _find_sheet(sheets: dict, prefer: list[str]) -> tuple[str, pd.DataFrame] | tuple[None, None]:
            for p in prefer:
                for k, df in sheets.items():
                    if k.lower() == p.lower():
                        return k, df
            # Fall back: first sheet with Customer Revenue column
            for k, df in sheets.items():
                if _find_col(df, ["Customer Revenue", "Revenue"]):
                    return k, df
            return None, None

        api_loads_name,  api_loads  = _find_sheet(api_data,    ["Loads",  "Load"])
        api_trips_name,  api_trips  = _find_sheet(api_data,    ["Trips",  "Trip"])
        man_loads_name,  man_loads  = _find_sheet(manual_data, ["Loads",  "Load"])
        man_trips_name,  man_trips  = _find_sheet(manual_data, ["Trips",  "Trip"])

        if api_loads is None:
            log_fn("✗ No Loads sheet found in API data.")
            return False

        log_fn(f"API Loads  : '{api_loads_name}' — {len(api_loads):,} rows")
        if api_trips is not None:
            log_fn(f"API Trips  : '{api_trips_name}' — {len(api_trips):,} rows")
        if man_loads is not None:
            log_fn(f"Manual Loads: '{man_loads_name}' — {len(man_loads):,} rows")
        if man_trips is not None:
            log_fn(f"Manual Trips: '{man_trips_name}' — {len(man_trips):,} rows")

        # ── Overlay Driver Rate ───────────────────────────────────────────
        log_fn("\nOverlaying X-Trux Driver Rate …")
        if man_loads is not None:
            api_loads, n_loads, n_load_api = _overlay_driver_rate(
                api_loads, man_loads, log_fn)
            log_fn(f"  Loads: {n_loads:,} rows updated from manual, "
                   f"{n_load_api:,} rows kept from API")
        else:
            log_fn("  ⚠  No manual Loads sheet — Driver Rate unchanged (API only)")
            n_loads = 0

        if api_trips is not None and man_trips is not None:
            api_trips, n_trips, n_trip_api = _overlay_driver_rate(
                api_trips, man_trips, log_fn)
            log_fn(f"  Trips: {n_trips:,} rows updated from manual, "
                   f"{n_trip_api:,} rows kept from API")
        elif api_trips is not None:
            log_fn("  ℹ  No manual Trips sheet — Trips Driver Rate unchanged")

        if n_loads == 0 and (api_trips is None or man_trips is None):
            log_fn("⚠  No Driver Rate rows were updated. "
                   "Check that Load # columns match between API and manual files.")

        # ── Build output workbook ─────────────────────────────────────────
        log_fn("\nBuilding combined workbook …")
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            api_loads.to_excel(writer, sheet_name="Loads", index=False)
            if api_trips is not None:
                api_trips.to_excel(writer, sheet_name="Trips", index=False)
            # Pass through any other sheets from the API file (e.g. Fuel)
            for name, df in api_data.items():
                if name not in (api_loads_name, api_trips_name) and name:
                    df.to_excel(writer, sheet_name=name, index=False)
        buf.seek(0)

        # ── Upload or save ────────────────────────────────────────────────
        if upload:
            log_fn("\nConnecting to OneDrive …")
            creds = _get_credentials()
            if not creds:
                log_fn("✗ Missing Azure / OneDrive credentials in .env file.")
                return False

            from src.onedrive_upload import get_token, ensure_folder, upload_file

            token = get_token(creds["tenant"], creds["client"], creds["secret"])
            log_fn("  Token OK")
            if creds["folder"]:
                ensure_folder(token, creds["upn"], creds["folder"])

            tmp = Path("/tmp") / target_name
            tmp.write_bytes(buf.getvalue())
            log_fn(f"Uploading '{target_name}' …")
            upload_file(token, creds["upn"], creds["folder"], target_name, tmp)
            tmp.unlink(missing_ok=True)
            log_fn(f"✓ Uploaded to OneDrive: {target_name}")
        else:
            out = Path(save_path) if save_path else Path.home() / "Downloads" / target_name
            out.write_bytes(buf.getvalue())
            log_fn(f"✓ Saved to: {out}")

        return True

    except Exception as exc:
        log_fn(f"✗ Error: {exc}")
        log.exception("process_and_upload failed")
        return False


# ── GUI widgets ───────────────────────────────────────────────────────────────

class FileCard(tk.Frame):
    """A card that shows a file source — either downloaded from OneDrive or browsed."""

    def __init__(self, master, title: str, subtitle: str,
                 show_download: bool = False, accept_dnd: bool = False, **kw):
        super().__init__(master, bg=CARD, bd=0,
                         highlightthickness=1, highlightbackground=BORDER, **kw)
        self._sheets: dict[str, pd.DataFrame] | None = None
        self._show_download = show_download
        self._accept_dnd    = accept_dnd

        # Title row
        hdr = tk.Frame(self, bg=CARD)
        hdr.pack(fill="x", padx=14, pady=(14, 0))
        tk.Label(hdr, text=title, font=("SF Pro", 13, "bold"),
                 bg=CARD, fg=TEXT).pack(side="left")

        tk.Label(self, text=subtitle, font=("SF Pro", 10),
                 bg=CARD, fg=MUTED, justify="left").pack(
                     anchor="w", padx=14, pady=(2, 10))

        # Buttons
        btn_row = tk.Frame(self, bg=CARD)
        btn_row.pack(fill="x", padx=14, pady=(0, 4))

        if show_download:
            self._dl_btn = tk.Button(
                btn_row, text="⬇  Download from OneDrive",
                font=("SF Pro", 11), bg=ACCENT, fg="white",
                activebackground=ACCHOV, relief="flat", padx=10, pady=6,
                cursor="hand2", command=self._download,
            )
            self._dl_btn.pack(side="left", padx=(0, 8))

        browse_txt = "Browse…" if show_download else "📂  Browse for file"
        tk.Button(
            btn_row, text=browse_txt,
            font=("SF Pro", 11), bg=PANEL, fg=TEXT,
            activebackground=BORDER, relief="flat", padx=10, pady=6,
            cursor="hand2",
            highlightthickness=1, highlightbackground=BORDER,
            command=self._browse,
        ).pack(side="left")

        # Drop hint
        if accept_dnd:
            tk.Label(self, text="or drag a file here",
                     font=("SF Pro", 10), bg=CARD, fg=MUTED).pack()

        # Status label
        self._status = tk.Label(self, text="No file loaded",
                                font=("SF Pro", 11), bg=CARD, fg=MUTED,
                                wraplength=280, justify="left")
        self._status.pack(anchor="w", padx=14, pady=(6, 14))

        if accept_dnd:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

        for w in (self, self._status):
            w.bind("<Enter>", lambda _: None)

    # ── file loading ──────────────────────────────────────────────────────

    def _browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")])
        if p:
            self._load_file(p)

    def _on_drop(self, event):
        raw = event.data.strip()
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        self._load_file(raw.split("} {")[0] if "} {" in raw else raw)

    def _load_file(self, path: str):
        self._set_status("⏳  Loading …", MUTED)
        def worker():
            try:
                sheets = _read_all_sheets(path)
                self._sheets = sheets
                names = list(sheets.keys())
                total = sum(len(df) for df in sheets.values())
                desc = (f"✓ {Path(path).name}\n"
                        f"Sheets: {', '.join(names)}\n"
                        f"{total:,} rows total")
                self.after(0, self._set_status, desc, SUCCESS)
                self.after(0, self.event_generate, "<<FileLoaded>>")
            except Exception as e:
                self.after(0, self._set_status, f"✗ {e}", ERROR)
        threading.Thread(target=worker, daemon=True).start()

    def _download(self):
        creds = _get_credentials()
        if not creds:
            messagebox.showerror("Missing credentials",
                                 "Azure / OneDrive credentials missing in .env")
            return
        self._set_status("⏳  Downloading from OneDrive …", MUTED)
        if hasattr(self, "_dl_btn"):
            self._dl_btn.config(state="disabled")
        def worker():
            try:
                from src.onedrive_upload import get_token, download_file
                token = get_token(creds["tenant"], creds["client"], creds["secret"])
                folder = creds["folder"]
                fname  = "Alvys Pipeline.xlsx"
                path   = f"{folder}/{fname}" if folder else fname
                raw    = download_file(token, creds["upn"], path)
                sheets = _read_all_sheets(raw)
                self._sheets = sheets
                names  = list(sheets.keys())
                total  = sum(len(df) for df in sheets.values())
                desc   = (f"✓ {fname} (from OneDrive)\n"
                          f"Sheets: {', '.join(names)}\n"
                          f"{total:,} rows total")
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
        self._set_status("No file loaded", MUTED)


# ── main window ───────────────────────────────────────────────────────────────

class App(tk.Tk if not _DND else TkinterDnD.Tk):  # type: ignore[misc]

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
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _build(self):
        # ── header ───────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Alvys Master Fixer",
                 font=("SF Pro", 18, "bold"), bg=PANEL, fg=TEXT,
                 pady=16).pack(side="left", padx=24)
        tk.Label(hdr,
                 text="API data + manual Driver Rate  →  OneDrive master file",
                 font=("SF Pro", 11), bg=PANEL, fg=MUTED).pack(side="left")

        # ── two cards ─────────────────────────────────────────────────────
        cards = tk.Frame(self, bg=BG)
        cards.pack(padx=20, pady=20, fill="x")

        self._api_card = FileCard(
            cards,
            title="① API Pipeline Data",
            subtitle="All load/trip fields from Alvys API.\nDownload the latest run from OneDrive, or browse.",
            show_download=True,
            accept_dnd=_DND,
            width=300,
        )
        self._api_card.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self._api_card.bind("<<FileLoaded>>", self._on_file_change)

        self._man_card = FileCard(
            cards,
            title="② Manual TMS Export",
            subtitle="For X-Trux Driver Rate (actual settled amounts).\nDrop your Alvys export here.",
            show_download=False,
            accept_dnd=_DND,
            width=300,
        )
        self._man_card.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self._man_card.bind("<<FileLoaded>>", self._on_file_change)

        if not _DND:
            tk.Label(self, text="💡 pip install tkinterdnd2  to enable drag-and-drop",
                     font=("SF Pro", 10), bg=BG, fg=MUTED).pack()

        # ── merge summary label ───────────────────────────────────────────
        self._summary = tk.Label(
            self,
            text="Load both files to see merge preview.",
            font=("SF Pro", 11), bg=BG, fg=MUTED,
            wraplength=620, justify="left",
        )
        self._summary.pack(anchor="w", padx=24, pady=(0, 4))

        # ── options row ───────────────────────────────────────────────────
        opts = tk.Frame(self, bg=BG)
        opts.pack(padx=24, pady=(4, 0), fill="x")

        tk.Label(opts, text="Output filename:",
                 font=("SF Pro", 12), bg=BG, fg=TEXT).pack(side="left")
        self._name_var = tk.StringVar(value="Alvys Master 2026.xlsx")
        tk.Entry(opts, textvariable=self._name_var,
                 font=("SF Pro", 12), bg=PANEL, fg=TEXT,
                 insertbackground=TEXT, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 width=30).pack(side="left", padx=(8, 0), ipady=4)

        # ── action buttons ────────────────────────────────────────────────
        btns = tk.Frame(self, bg=BG)
        btns.pack(padx=24, pady=14, fill="x")

        self._upload_btn = tk.Button(
            btns, text="⬆  Merge & Upload to OneDrive",
            font=("SF Pro", 13, "bold"),
            bg=ACCENT, fg="white", activebackground=ACCHOV,
            relief="flat", bd=0, cursor="hand2", padx=18, pady=10,
            state="disabled",
            command=lambda: self._run(upload=True),
        )
        self._upload_btn.pack(side="left", padx=(0, 10))

        self._save_btn = tk.Button(
            btns, text="💾  Merge & Save Locally",
            font=("SF Pro", 13),
            bg=PANEL, fg=TEXT, activebackground=BORDER,
            relief="flat", bd=0, cursor="hand2", padx=18, pady=10,
            highlightthickness=1, highlightbackground=BORDER,
            state="disabled",
            command=lambda: self._run(upload=False),
        )
        self._save_btn.pack(side="left")

        tk.Button(
            btns, text="↺  Reset",
            font=("SF Pro", 12),
            bg=PANEL, fg=MUTED, activebackground=BORDER,
            relief="flat", bd=0, cursor="hand2", padx=12, pady=10,
            command=self._reset,
        ).pack(side="right")

        # ── log ───────────────────────────────────────────────────────────
        lf = tk.Frame(self, bg=BG)
        lf.pack(padx=24, pady=(0, 20), fill="both")

        self._log = tk.Text(
            lf, height=10, bg=PANEL, fg=TEXT,
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

        self._log_write("Ready — load API data and manual export to begin.", "info")

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_file_change(self, _=None):
        api = self._api_card.sheets
        man = self._man_card.sheets

        if api and man:
            self._update_summary(api, man)
            self._upload_btn.config(state="normal")
            self._save_btn.config(state="normal")
        elif api:
            self._summary.config(
                text="✓ API data loaded. Now load the manual TMS export.",
                fg=WARNING)
            self._upload_btn.config(state="disabled")
            self._save_btn.config(state="disabled")
        else:
            self._summary.config(text="Load both files to see merge preview.", fg=MUTED)
            self._upload_btn.config(state="disabled")
            self._save_btn.config(state="disabled")

    def _update_summary(self, api: dict, man: dict):
        """Show a quick merge preview in the summary label."""
        try:
            # Find Loads sheets
            api_loads = next(
                (df for k, df in api.items() if k.lower() in ("loads", "load")), None)
            man_loads = next(
                (df for k, df in man.items() if k.lower() in ("loads", "load")), None)

            if api_loads is None or man_loads is None:
                self._summary.config(
                    text="✓ Both files loaded — ready to merge.", fg=SUCCESS)
                return

            man_dr_col = _find_col(man_loads, ["Driver Rate", "DriverRate"])
            man_id_col = _find_col(man_loads, ["Load #", "Load Number", "LoadNumber"])
            api_id_col = _find_col(api_loads, ["Load #", "Load Number", "LoadNumber"])

            if man_dr_col and man_id_col and api_id_col:
                man_with_dr = int(
                    (pd.to_numeric(man_loads[man_dr_col], errors="coerce").fillna(0) > 0).sum()
                )
                txt = (
                    f"✓ Ready to merge.  "
                    f"API: {len(api_loads):,} loads  ·  "
                    f"Manual: {len(man_loads):,} loads, "
                    f"{man_with_dr:,} with Driver Rate  →  "
                    f"will overlay on matching Load #s"
                )
            else:
                txt = f"✓ Both files loaded — ready to merge."

            self._summary.config(text=txt, fg=SUCCESS)
        except Exception:
            self._summary.config(text="✓ Both files loaded — ready to merge.", fg=SUCCESS)

    def _run(self, upload: bool):
        api = self._api_card.sheets
        man = self._man_card.sheets
        if not api or not man:
            messagebox.showwarning("Not ready", "Load both files first.")
            return

        name = self._name_var.get().strip() or "Alvys Master 2026.xlsx"
        save_path = None
        if not upload:
            save_path = filedialog.asksaveasfilename(
                initialfile=name,
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
            )
            if not save_path:
                return

        self._set_busy(True)
        self._log_write("─" * 50, "info")

        def worker():
            ok = process_and_upload(
                api_data=api,
                manual_data=man,
                target_name=name,
                upload=upload,
                save_path=save_path,
                log_fn=lambda m: self.after(0, self._log_write, m),
            )
            def done():
                self._set_busy(False)
                if ok:
                    dest = "OneDrive" if upload else save_path
                    messagebox.showinfo("Done", f"✓ {name}\n→ {dest}")
            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy(self, busy: bool):
        s = "disabled" if busy else "normal"
        self._upload_btn.config(state=s,
            text="⏳  Working …" if busy else "⬆  Merge & Upload to OneDrive")
        self._save_btn.config(state=s)

    def _log_write(self, msg: str, tag: str = "info"):
        if msg.startswith("✓"):   tag = "ok"
        elif msg.startswith("⚠"): tag = "warn"
        elif msg.startswith("✗"): tag = "err"
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n", tag)
        self._log.see("end")
        self._log.config(state="disabled")

    def _reset(self):
        self._api_card.reset()
        self._man_card.reset()
        self._on_file_change()
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")
        self._log_write("Ready — load API data and manual export to begin.", "info")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
