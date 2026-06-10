"""
Alvys Master Fixer — desktop GUI tool.

Accepts the two Alvys TMS exports (Loads + Trips), fixes Driver Rate for
X-Linx brokered loads (copies Carrier Rate → Driver Rate where Driver Rate=0),
recomputes Gross Margin, combines into one workbook, and uploads to OneDrive
as "Alvys Master 2026.xlsx" (or another name you choose).

Run directly:
    python -m src.master_fixer_gui

Or double-click "Alvys Master Fixer.command" on the desktop.
"""
from __future__ import annotations

import io
import logging
import os
import sys
import threading
from pathlib import Path

import pandas as pd

# ── optional drag-and-drop support ──────────────────────────────────────────
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND = True
except ImportError:
    _DND = False

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ── load .env so OneDrive creds are available ────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(_env_path)
except Exception:
    pass

log = logging.getLogger("master_fixer_gui")


# ── colours / style ──────────────────────────────────────────────────────────
BG         = "#1e1e2e"
PANEL      = "#2a2a3e"
ACCENT     = "#7c6af7"
ACCENT_HOV = "#9d8fff"
SUCCESS    = "#50fa7b"
WARNING    = "#f1fa8c"
ERROR      = "#ff5555"
TEXT       = "#f8f8f2"
MUTED      = "#888899"
BORDER     = "#44475a"
DROP_IDLE  = "#2a2a3e"
DROP_HOV   = "#3a3a5e"
DROP_READY = "#1e3a2e"


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cl = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in df.columns:
            return c
        if c.lower() in cl:
            return cl[c.lower()]
    return None


def _fix_sheet(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Fix Driver Rate → Carrier Rate fallback; recompute Gross Margin.
    Returns (fixed_df, n_patched)."""
    dr_col  = _find_col(df, ["Driver Rate", "DriverRate"])
    cr_col  = _find_col(df, ["Carrier Rate", "CarrierRate"])
    rev_col = _find_col(df, ["Customer Revenue", "Revenue"])
    gm_col  = _find_col(df, ["Gross Margin", "GrossMargin", "Margin"])

    if not dr_col or not cr_col:
        return df, 0

    dr  = pd.to_numeric(df[dr_col],  errors="coerce").fillna(0)
    cr  = pd.to_numeric(df[cr_col],  errors="coerce").fillna(0)
    mask = (dr == 0) & (cr > 0)
    n   = int(mask.sum())

    df = df.copy()
    df[dr_col] = dr.where(~mask, cr)

    if gm_col and rev_col:
        rev = pd.to_numeric(df[rev_col], errors="coerce").fillna(0)
        new_dr = pd.to_numeric(df[dr_col], errors="coerce").fillna(0)
        df[gm_col] = rev - new_dr

    return df, n


def _best_sheet(xl: pd.ExcelFile) -> str:
    """Return the sheet name most likely to be the main data sheet."""
    for name in xl.sheet_names:
        df = xl.parse(name, nrows=3)
        if _find_col(df, ["Customer Revenue", "Revenue"]):
            return name
    return xl.sheet_names[0]


def process_and_upload(
    loads_path: str,
    trips_path: str,
    target_name: str,
    upload: bool,
    log_fn,
) -> bool:
    """Core worker — runs on a background thread. Returns True on success."""
    try:
        # ── read ─────────────────────────────────────────────────────────────
        log_fn(f"Reading Loads file: {Path(loads_path).name}")
        loads_xl = pd.ExcelFile(loads_path, engine="openpyxl")
        loads_sheet = _best_sheet(loads_xl)
        loads_df = loads_xl.parse(loads_sheet)
        log_fn(f"  → sheet '{loads_sheet}': {len(loads_df):,} rows")

        log_fn(f"Reading Trips file: {Path(trips_path).name}")
        trips_xl = pd.ExcelFile(trips_path, engine="openpyxl")
        trips_sheet = _best_sheet(trips_xl)
        trips_df = trips_xl.parse(trips_sheet)
        log_fn(f"  → sheet '{trips_sheet}': {len(trips_df):,} rows")

        # ── fix ──────────────────────────────────────────────────────────────
        log_fn("Fixing Driver Rate …")
        loads_df, n_loads = _fix_sheet(loads_df)
        trips_df, n_trips = _fix_sheet(trips_df)
        log_fn(f"  Loads: {n_loads} row(s) patched")
        log_fn(f"  Trips: {n_trips} row(s) patched")

        if n_loads == 0 and n_trips == 0:
            log_fn("⚠  No rows needed patching — Driver Rate already populated.")

        # ── write to buffer ──────────────────────────────────────────────────
        log_fn("Building combined workbook …")
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            loads_df.to_excel(writer, sheet_name="Loads",  index=False)
            trips_df.to_excel(writer, sheet_name="Trips",  index=False)
        buf.seek(0)

        # ── upload or save ───────────────────────────────────────────────────
        if upload:
            log_fn("Connecting to OneDrive …")
            tenant   = os.environ.get("AZURE_TENANT_ID",     "")
            client   = os.environ.get("AZURE_CLIENT_ID",     "")
            secret   = os.environ.get("AZURE_CLIENT_SECRET", "")
            upn      = os.environ.get("ONEDRIVE_USER_UPN",   "")
            folder   = os.environ.get("ONEDRIVE_FOLDER_PATH", "")

            missing = [k for k, v in {
                "AZURE_TENANT_ID": tenant, "AZURE_CLIENT_ID": client,
                "AZURE_CLIENT_SECRET": secret, "ONEDRIVE_USER_UPN": upn,
            }.items() if not v]
            if missing:
                log_fn(f"✗ Missing credentials in .env: {', '.join(missing)}")
                return False

            from src.onedrive_upload import get_token, ensure_folder, upload_file

            token = get_token(tenant, client, secret)
            log_fn("  Token OK")

            if folder:
                ensure_folder(token, upn, folder)

            tmp = Path("/tmp") / target_name
            tmp.write_bytes(buf.getvalue())

            log_fn(f"Uploading as '{target_name}' …")
            upload_file(token, upn, folder, target_name, tmp)
            tmp.unlink(missing_ok=True)
            log_fn(f"✓ Uploaded to OneDrive: {target_name}")
        else:
            save_path = Path(loads_path).parent / target_name
            save_path.write_bytes(buf.getvalue())
            log_fn(f"✓ Saved locally: {save_path}")

        return True

    except Exception as exc:
        log_fn(f"✗ Error: {exc}")
        log.exception("process_and_upload failed")
        return False


# ── GUI ───────────────────────────────────────────────────────────────────────

class DropZone(tk.Frame):
    """A click-to-browse file selector that also accepts DnD when available."""

    def __init__(self, master, label: str, accept_dnd: bool = False, **kw):
        super().__init__(master, bg=DROP_IDLE, bd=0, highlightthickness=2,
                         highlightbackground=BORDER, **kw)
        self._path: str | None = None
        self._label = label
        self._accept_dnd = accept_dnd

        self._icon = tk.Label(self, text="📂", font=("SF Pro", 28), bg=DROP_IDLE,
                              fg=MUTED, cursor="hand2")
        self._icon.pack(pady=(18, 4))

        self._title = tk.Label(self, text=label, font=("SF Pro", 13, "bold"),
                               bg=DROP_IDLE, fg=TEXT)
        self._title.pack()

        self._hint = tk.Label(self,
                              text="Drag file here\nor click to browse" if accept_dnd
                                   else "Click to browse",
                              font=("SF Pro", 11), bg=DROP_IDLE, fg=MUTED,
                              justify="center")
        self._hint.pack(pady=(4, 0))

        self._file_lbl = tk.Label(self, text="", font=("SF Pro", 10),
                                  bg=DROP_IDLE, fg=SUCCESS,
                                  wraplength=220, justify="center")
        self._file_lbl.pack(pady=(6, 16), padx=10)

        for w in (self, self._icon, self._title, self._hint, self._file_lbl):
            w.bind("<Button-1>", self._browse)
            w.bind("<Enter>",    self._hover_on)
            w.bind("<Leave>",    self._hover_off)

        if accept_dnd:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _browse(self, _=None):
        p = filedialog.askopenfilename(
            title=f"Select {self._label}",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
        )
        if p:
            self.set_path(p)

    def _on_drop(self, event):
        raw = event.data.strip()
        # tkinterdnd2 wraps paths with spaces in {}
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        # take the first file if multiple dropped
        path = raw.split("} {")[0] if "} {" in raw else raw
        self.set_path(path)

    def set_path(self, path: str):
        self._path = path
        name = Path(path).name
        short = name if len(name) <= 30 else name[:27] + "…"
        self._file_lbl.config(text=f"✓ {short}")
        self._set_bg(DROP_READY)
        self.event_generate("<<FileSelected>>")

    def _hover_on(self, _=None):
        if not self._path:
            self._set_bg(DROP_HOV)

    def _hover_off(self, _=None):
        if not self._path:
            self._set_bg(DROP_IDLE)

    def _set_bg(self, colour: str):
        self.config(bg=colour, highlightbackground=ACCENT if colour == DROP_READY else BORDER)
        for w in (self._icon, self._title, self._hint, self._file_lbl):
            w.config(bg=colour)

    @property
    def path(self) -> str | None:
        return self._path

    def reset(self):
        self._path = None
        self._file_lbl.config(text="")
        self._set_bg(DROP_IDLE)


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
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build(self):
        # ── header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Alvys Master Fixer",
                 font=("SF Pro", 18, "bold"), bg=PANEL, fg=TEXT,
                 pady=18).pack(side="left", padx=24)
        tk.Label(hdr,
                 text="Fixes X-Linx Driver Rate · Combines Loads + Trips · Uploads to OneDrive",
                 font=("SF Pro", 11), bg=PANEL, fg=MUTED).pack(side="left")

        # ── drop zones ───────────────────────────────────────────────────────
        zones = tk.Frame(self, bg=BG)
        zones.pack(padx=24, pady=20)

        self._loads_zone = DropZone(zones, "Loads Export", accept_dnd=_DND,
                                    width=240, height=160)
        self._loads_zone.pack(side="left", padx=(0, 12))
        self._loads_zone.bind("<<FileSelected>>", self._on_file_change)

        arrow = tk.Label(zones, text="➕", font=("SF Pro", 22),
                         bg=BG, fg=MUTED)
        arrow.pack(side="left", padx=4)

        self._trips_zone = DropZone(zones, "Trips Export", accept_dnd=_DND,
                                    width=240, height=160)
        self._trips_zone.pack(side="left", padx=(12, 0))
        self._trips_zone.bind("<<FileSelected>>", self._on_file_change)

        if not _DND:
            tk.Label(self,
                     text="💡 pip install tkinterdnd2  to enable drag-and-drop",
                     font=("SF Pro", 10), bg=BG, fg=MUTED).pack()

        # ── options row ──────────────────────────────────────────────────────
        opts = tk.Frame(self, bg=BG)
        opts.pack(padx=24, pady=(4, 0), fill="x")

        tk.Label(opts, text="Output filename:", font=("SF Pro", 12),
                 bg=BG, fg=TEXT).pack(side="left")

        self._name_var = tk.StringVar(value="Alvys Master 2026.xlsx")
        name_entry = tk.Entry(opts, textvariable=self._name_var,
                              font=("SF Pro", 12), bg=PANEL, fg=TEXT,
                              insertbackground=TEXT, relief="flat",
                              highlightthickness=1, highlightbackground=BORDER,
                              width=28)
        name_entry.pack(side="left", padx=(8, 0), ipady=4)

        # ── buttons ──────────────────────────────────────────────────────────
        btns = tk.Frame(self, bg=BG)
        btns.pack(padx=24, pady=16, fill="x")

        self._upload_btn = tk.Button(
            btns,
            text="⬆  Fix & Upload to OneDrive",
            font=("SF Pro", 13, "bold"),
            bg=ACCENT, fg="white", activebackground=ACCENT_HOV,
            relief="flat", bd=0, cursor="hand2", padx=20, pady=10,
            state="disabled",
            command=lambda: self._run(upload=True),
        )
        self._upload_btn.pack(side="left", padx=(0, 10))

        self._save_btn = tk.Button(
            btns,
            text="💾  Fix & Save Locally",
            font=("SF Pro", 13),
            bg=PANEL, fg=TEXT, activebackground=BORDER,
            relief="flat", bd=0, cursor="hand2", padx=20, pady=10,
            highlightthickness=1, highlightbackground=BORDER,
            state="disabled",
            command=lambda: self._run(upload=False),
        )
        self._save_btn.pack(side="left")

        self._reset_btn = tk.Button(
            btns,
            text="↺",
            font=("SF Pro", 13),
            bg=PANEL, fg=MUTED, activebackground=BORDER,
            relief="flat", bd=0, cursor="hand2", padx=12, pady=10,
            command=self._reset,
        )
        self._reset_btn.pack(side="right")

        # ── log ──────────────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=BG)
        log_frame.pack(padx=24, pady=(0, 20), fill="both")

        self._log = tk.Text(log_frame, height=10, bg=PANEL, fg=TEXT,
                            font=("SF Mono", 11), relief="flat",
                            highlightthickness=1, highlightbackground=BORDER,
                            state="disabled", wrap="word")
        scroll = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.config(yscrollcommand=scroll.set)
        self._log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._log.tag_config("ok",   foreground=SUCCESS)
        self._log.tag_config("warn", foreground=WARNING)
        self._log.tag_config("err",  foreground=ERROR)
        self._log.tag_config("info", foreground=TEXT)

        self._append_log("Ready — select a Loads and Trips export to begin.", "info")

    def _on_file_change(self, _=None):
        ready = bool(self._loads_zone.path and self._trips_zone.path)
        state = "normal" if ready else "disabled"
        self._upload_btn.config(state=state)
        self._save_btn.config(state=state)

    def _append_log(self, msg: str, tag: str = "info"):
        self._log.config(state="normal")
        if msg.startswith("✓"):
            tag = "ok"
        elif msg.startswith("⚠") or msg.startswith("Warning"):
            tag = "warn"
        elif msg.startswith("✗") or msg.startswith("Error"):
            tag = "err"
        self._log.insert("end", msg + "\n", tag)
        self._log.see("end")
        self._log.config(state="disabled")

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self._upload_btn.config(state=state)
        self._save_btn.config(state=state, cursor="arrow" if busy else "hand2")
        if busy:
            self._upload_btn.config(text="⏳  Working …")
        else:
            self._upload_btn.config(text="⬆  Fix & Upload to OneDrive")

    def _run(self, upload: bool):
        lp = self._loads_zone.path
        tp = self._trips_zone.path
        nm = self._name_var.get().strip() or "Alvys Master 2026.xlsx"

        self._set_busy(True)
        self._append_log("─" * 48, "info")

        def worker():
            ok = process_and_upload(
                loads_path=lp,
                trips_path=tp,
                target_name=nm,
                upload=upload,
                log_fn=lambda m: self.after(0, self._append_log, m),
            )
            def done():
                self._set_busy(False)
                if ok:
                    messagebox.showinfo(
                        "Done",
                        f"✓ {'Uploaded to OneDrive' if upload else 'Saved locally'}: {nm}",
                    )
            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _reset(self):
        self._loads_zone.reset()
        self._trips_zone.reset()
        self._on_file_change()
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")
        self._append_log("Ready — select a Loads and Trips export to begin.", "info")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
