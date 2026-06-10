#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Alvys Master Fixer — double-click to open the desktop tool
# Place this file on your Mac Desktop and double-click to launch.
# ─────────────────────────────────────────────────────────────

REPO="$HOME/alvys-pipeline"
VENV="$REPO/.venv"

# Activate the virtual environment
if [ ! -f "$VENV/bin/activate" ]; then
    echo "Setting up virtual environment for the first time..."
    python3 -m venv "$VENV"
    source "$VENV/bin/activate"
    pip install -r "$REPO/requirements.txt" --quiet
else
    source "$VENV/bin/activate"
fi

# Install tkinterdnd2 for drag-and-drop support (safe to re-run)
pip install tkinterdnd2 --quiet 2>/dev/null

# Launch the GUI
cd "$REPO"
python -m src.master_fixer_gui
