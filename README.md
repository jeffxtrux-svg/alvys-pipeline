# Alvys → Power BI Data Pipeline

Pulls Loads, Trips, and Fuel data from the Alvys API and produces an
`Alvys_Master.xlsx` file matching the schema you currently use in Power BI.

Designed to grow into a multi-source hub: Alvys today, Samsara and QuickBooks
next, all feeding one OneDrive folder that Power BI reads from.

## Status

| Phase | What it does                                  | Status                |
|-------|----------------------------------------------|-----------------------|
| 1     | Pull Alvys → write Excel locally             | ✅ Built (you are here)|
| 2     | GitHub Actions runs it 3x/day                | 🔧 Workflow included, disabled |
| 3     | Upload output to OneDrive via Microsoft Graph| 🔜 Next               |
| 4     | Add Samsara connector                        | 🔜 Future             |
| 5     | Add QuickBooks (5 companies) connector       | 🔜 Future             |

---

## Phase 1 — Get it running locally (15 minutes)

You need: a computer with Python 3.10+ installed, and your Alvys client ID + secret.

### 1. Get the code onto your machine

```bash
# Clone or copy this folder somewhere on your computer, e.g.:
cd ~/Documents
git clone https://github.com/YOUR_USERNAME/alvys-pipeline.git
cd alvys-pipeline
```

If you haven't pushed it to GitHub yet, just copy this folder there directly.

### 2. Install Python dependencies

```bash
python -m venv .venv

# Mac/Linux:
source .venv/bin/activate

# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Set your credentials

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in:
- `ALVYS_CLIENT_ID` — from Alvys → Settings → API/Integrations
- `ALVYS_CLIENT_SECRET` — same place

### 4. Run it

```bash
python -m src.main
```

You should see log output for each step (auth, fetching loads, fetching trips,
fetching fuel, transforming, writing). The full run takes 2–10 minutes
depending on how much history you're pulling.

### 5. Check the output

A new file appears at `output/Alvys_Master.xlsx`. Open it and compare against
your current `Alvys_Master.xlsx`:

- Sheet names should match: **Fuel**, **Loads**, **Trips**
- Column names and order should match exactly
- Row counts should be similar (within a few percent — Alvys is a moving target)

**If some columns are blank** when they shouldn't be: the log output will list
them at the end. That means a field name in `src/column_mappings.py` doesn't
match what the API actually returns. Just edit the path string for that column
and re-run. No code changes needed.

---

## Phase 2 — Automate it on GitHub Actions (30 min)

Once Phase 1 works locally, push this repo to GitHub (private repo recommended)
and configure secrets:

1. **Push to GitHub** (private repo is fine — Actions still has 2000 free min/mo)

2. **Add repository secrets** at *Settings → Secrets and variables → Actions*:
   - `ALVYS_CLIENT_ID`
   - `ALVYS_CLIENT_SECRET`

3. **Test the workflow manually**:
   - Go to the Actions tab in your repo
   - Click "Refresh Alvys data" → "Run workflow"
   - Watch it run. When it finishes, download the artifact from the run page.
   - Open the downloaded `Alvys_Master.xlsx` — should match Phase 1 output.

4. **Enable the schedule** in `.github/workflows/refresh.yml`:
   - Uncomment the `schedule:` block
   - Commit and push

The workflow will now run automatically 3x/day. You can check the Actions tab
anytime to see run history and download outputs.

---

## Phase 3 — Upload to OneDrive (next chat)

Once Phase 2 is producing the artifact correctly, we'll add a step that uses
Microsoft Graph API to push `Alvys_Master.xlsx` into a specific OneDrive folder.
Power BI will be pointed at that folder and refresh from the latest file.

---

## Troubleshooting

**`401 Unauthorized` from Alvys**
- Double-check client ID and secret in `.env`
- Confirm in Alvys Settings → API/Integrations that the credentials are active

**`HTTPError: 429` (rate limited)**
- The script paginates with a 0.2s delay between pages. If this still trips,
  bump the `time.sleep(0.2)` in `src/alvys_client.py` to 0.5

**Some columns are entirely blank**
- Expected on first run — the log lists which ones. Update `src/column_mappings.py`
  with the actual API field name (inspect a raw record with: `python -c "from src.alvys_client import AlvysClient; import json; c=AlvysClient('...','...'); print(json.dumps(c.fetch_loads('2024-01-01')[0], indent=2))"`)

**Date columns showing as text in Power BI**
- Excel keeps them as ISO strings. In Power Query, set the column type to
  Date/Time. Power BI usually auto-detects on next refresh.

---

## Project structure

```
alvys-pipeline/
├── .github/workflows/refresh.yml    # Phase 2 automation
├── src/
│   ├── alvys_client.py              # OAuth + paginated API calls
│   ├── column_mappings.py           # ← edit here if columns come back blank
│   ├── transformers.py              # JSON → DataFrame
│   ├── output_writer.py             # Excel writer
│   └── main.py                      # Entry point
├── .env.example                     # Credential template
├── .gitignore                       # Keeps .env and output/ out of git
├── requirements.txt                 # Python deps
└── README.md                        # This file
```
