"""QuickBooks OAuth refresh-token helper (interactive, one-off).

Run this once per QB company when refresh tokens have died (`invalid_grant`
on every pull). Walks through Intuit's consent screen in your browser,
captures the authorization code on `localhost:8080`, exchanges it for a
fresh refresh token, and prints exactly which GitHub Secret to paste it
into.

Setup (one time per machine):
  1. Make sure your Intuit Developer app
     (https://developer.intuit.com/app/developer/dashboard) has this
     redirect URI registered:
         http://localhost:8080/callback
     Use --port to choose a different port if 8080 is taken — and
     register the corresponding URI in the app dashboard.
  2. Have QB_CLIENT_ID and QB_CLIENT_SECRET in `.env` or shell env.
     These are the same secrets the pipeline already uses; copy from
     GitHub repo Secrets if you don't have them locally.

Usage:
    pip install -r requirements.txt   # if not already
    python -m src.qb_oauth_refresh    # once per company

Each run produces a refresh token for whichever QB company you select
on Intuit's "Which company do you want to connect?" screen. Re-run for
each of X-Trux, Truk-Way, and X-Linx to fix all three.
"""
from __future__ import annotations

import argparse
import base64
import http.server
import os
import sys
import urllib.parse
import webbrowser
from threading import Event

import requests
from dotenv import load_dotenv

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE = "com.intuit.quickbooks.accounting"
DEFAULT_PORT = 8080

# Realm-id -> (company-name, GitHub secret name) — keep in sync with
# src/qb_main.py:_companies() so the script can tell you exactly which
# secret to update without you having to look it up.
REALM_TO_SECRET: dict[str, tuple[str, str]] = {
    "9341454573269252": ("X-Trux Inc",       "QB_XTRUX_REFRESH_TOKEN"),
    "9341454569556134": ("Truk-Way Leasing", "QB_TRUKWAY_REFRESH_TOKEN"),
    "9341454574046601": ("X-Linx Inc",       "QB_XLINX_REFRESH_TOKEN"),
}


class _OAuthHandler(http.server.BaseHTTPRequestHandler):
    """Captures Intuit's OAuth redirect on localhost.

    Class-level state so the main thread can read the result without
    instantiating the handler itself (http.server creates the handler
    per-request).
    """
    captured: dict = {}
    done = Event()

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _OAuthHandler.captured = {
            "code": params.get("code", [None])[0],
            "realm_id": params.get("realmId", [None])[0],
            "state": params.get("state", [None])[0],
            "error": params.get("error", [None])[0],
            "error_description": params.get("error_description", [None])[0],
        }
        body = (
            "<html><body style='font-family:system-ui;max-width:560px;margin:60px auto;color:#222;'>"
            "<h2 style='margin:0 0 12px;'>QuickBooks authorization captured.</h2>"
            "<p>You can close this tab and return to the terminal — the script will print "
            "the new refresh token and tell you which GitHub Secret to update.</p>"
            "</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _OAuthHandler.done.set()

    def log_message(self, fmt, *args):
        # Silence the default access-log spam.
        return


def _exchange_code(code: str, client_id: str, client_secret: str,
                   redirect_uri: str) -> dict:
    """Exchange the OAuth authorization code for access + refresh tokens."""
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {creds}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed [{resp.status_code}]: {resp.text[:500]}")
    return resp.json()


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(
        description="Mint a fresh QuickBooks refresh token via interactive OAuth.")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"Local callback port (default {DEFAULT_PORT}). Must match "
                         "the redirect URI registered in your Intuit app.")
    ap.add_argument("--timeout", type=int, default=300,
                    help="Seconds to wait for the OAuth redirect (default 300).")
    args = ap.parse_args()

    client_id = os.environ.get("QB_CLIENT_ID")
    client_secret = os.environ.get("QB_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("ERROR: QB_CLIENT_ID and QB_CLIENT_SECRET required (set in .env or env vars).")

    redirect_uri = f"http://localhost:{args.port}/callback"
    # state is a CSRF guard — Intuit echoes it back and we verify it matches
    # what we sent before trusting the code.
    state = base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
    auth_url = (
        f"{AUTH_URL}?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "scope": SCOPE,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        })
    )

    print()
    print("=" * 72)
    print("  Intuit Developer app must have this redirect URI registered:")
    print(f"      {redirect_uri}")
    print("  Dashboard: https://developer.intuit.com/app/developer/dashboard")
    print("=" * 72)
    print()
    print("  Opening browser. On the Intuit screen, pick the QB company whose")
    print("  refresh token you want to mint (X-Trux, Truk-Way, or X-Linx).")
    print()
    print("  If the browser doesn't open, copy this URL manually:")
    print(f"      {auth_url}")
    print()

    server = http.server.HTTPServer(("127.0.0.1", args.port), _OAuthHandler)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print(f"  Listening on {redirect_uri}  ({args.timeout}s timeout). Ctrl-C to abort.")
    server.timeout = 1
    waited = 0
    while not _OAuthHandler.done.is_set() and waited < args.timeout:
        try:
            server.handle_request()
        except KeyboardInterrupt:
            server.server_close()
            sys.exit("\nAborted.")
        waited += 1
    server.server_close()

    if not _OAuthHandler.done.is_set():
        sys.exit("ERROR: Timed out waiting for OAuth redirect.")
    cap = _OAuthHandler.captured
    if cap.get("error"):
        sys.exit(f"ERROR: Intuit returned error={cap['error']}: "
                 f"{cap.get('error_description') or ''}")
    if cap.get("state") != state:
        sys.exit("ERROR: state mismatch — possible CSRF; aborting.")
    code = cap.get("code")
    realm = cap.get("realm_id")
    if not code or not realm:
        sys.exit("ERROR: missing code or realmId in Intuit's redirect.")

    print(f"  Got authorization code for realm {realm}. Exchanging for tokens…")
    tokens = _exchange_code(code, client_id, client_secret, redirect_uri)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        sys.exit(f"ERROR: token exchange succeeded but no refresh_token in response: {tokens}")

    # Best-effort: name the company + which GitHub Secret it goes into.
    company, secret_name = REALM_TO_SECRET.get(realm, (None, None))
    print()
    print("=" * 72)
    if company:
        print(f"  Company:                 {company}")
        print(f"  Realm ID:                {realm}")
        print(f"  GitHub Secret to update: {secret_name}")
    else:
        print(f"  Realm ID:                {realm}  (no preset mapping — pick the matching")
        print( "                            GitHub secret yourself)")
    print()
    print("  New refresh token (valid ~100 days unless rotated):")
    print()
    print(f"    {refresh_token}")
    print()
    print("=" * 72)
    print()
    print("  Next steps:")
    if company:
        print( "    1. Open https://github.com/jeffxtrux-svg/alvys-pipeline/settings/secrets/actions")
        print(f"    2. Edit '{secret_name}', paste the token above as the new value, save.")
    else:
        print("    1. Paste the token into the right GitHub Secret for this realm.")
    print("    3. Re-run this script for the next company (do all 3 in one sitting so they")
    print("       don't drift apart).")
    print("    4. After all three are updated, fire the QuickBooks workflow once to confirm")
    print("       it rotates cleanly:")
    print("       https://github.com/jeffxtrux-svg/alvys-pipeline/actions/workflows/qb_refresh.yml")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
