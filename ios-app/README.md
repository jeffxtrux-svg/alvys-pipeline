# Alvys Pipeline — Personal iPhone App (PWA)

A fully on-device viewer for your `Alvys_Master.xlsx` pipeline output.
Open it on your iPhone, install to the home screen, and browse Loads,
Trips, and Fuel with a Dashboard and search. Works offline after first
load. **No data leaves your device.**

## What you get

- **Dashboard** — KPI cards (revenue, gross margin, miles, fuel spend,
  this week's activity) and a recent-loads list.
- **Loads / Trips / Fuel** — searchable, status-filterable lists; tap
  a row for the full record.
- **Settings** — set a default URL (e.g. a OneDrive share link) and
  reload with one tap; clear cached data.
- **Offline** — installs to your home screen and works without network
  after the first visit.

## Quickest setup (3 minutes)

You need a static host. GitHub Pages is the easiest for a personal app:

1. **Push the repo to GitHub** (if it isn't already).
2. In your repo on github.com, go to **Settings → Pages**:
   - Source: **Deploy from a branch**
   - Branch: pick `claude/personal-iphone-app-WpbJ8` (or `main` after merging) and folder `/ (root)`.
   - Save. Wait ~30 seconds.
3. Open the published URL on your iPhone — it will look like
   `https://<your-username>.github.io/alvys-pipeline/ios-app/`.
4. In Safari: tap the **Share** button → **Add to Home Screen** →
   **Add**.
5. Open the new "Alvys" icon on your home screen.

### Loading your data

The app needs your `Alvys_Master.xlsx`. Three ways:

1. **From Files** — tap **Choose file**, browse to the file on your
   iPhone (the Files app integrates with OneDrive, iCloud Drive, etc.).
2. **From URL** — tap **Load from URL…**, paste a direct download link
   (e.g. a OneDrive share link with `&download=1`, or a GitHub raw URL
   if you commit the file). The URL is remembered if you save it in
   Settings.
3. **Tap ↻** in the top bar — re-downloads from the saved URL, or
   re-opens the file picker if none is saved.

The parsed data is cached in your phone's IndexedDB; the app opens
straight to the Dashboard on subsequent visits.

## Alternative hosting

Anything that serves static files works:

- **Netlify / Vercel / Cloudflare Pages** — drag-and-drop the
  `ios-app/` folder; you get an HTTPS URL.
- **Self-hosted** — any HTTPS server. `python3 -m http.server` works
  for local testing on your laptop, but installing to iPhone home
  screen needs HTTPS (or `localhost`).

## Local development

```bash
cd ios-app
python3 -m http.server 8000
# Open http://localhost:8000 on your laptop.
# To test on iPhone over the same Wi-Fi, replace localhost with your
# laptop's LAN IP. Home-screen install requires HTTPS on a real domain.
```

## How it works

- `index.html` — app shell with view containers
- `app.js` — view routing, xlsx parsing, IndexedDB cache, rendering
- `styles.css` — iOS-flavored dark/light theme
- `manifest.webmanifest` + `service-worker.js` — PWA install + offline
- [SheetJS Community Edition](https://sheetjs.com/) — loaded from CDN
  on first visit, then cached by the service worker so subsequent
  visits work offline

The app deliberately has no backend. The `.xlsx` file is parsed in
the browser; only the rows in the workbook ever exist on the device.
Clearing site data (or **Settings → Clear cached data**) removes
everything.

## Notes / limitations

- iOS PWAs have a ~50 MB IndexedDB quota by default and may be evicted
  if storage is tight. Your master file is typically far smaller than
  that.
- "Load from URL" requires the host to allow cross-origin reads
  (CORS). OneDrive download links work; SharePoint internal links
  generally don't.
- This is an unsigned PWA — there is no App Store distribution. It's
  installed via Safari's "Add to Home Screen" and is private to your
  iPhone.
