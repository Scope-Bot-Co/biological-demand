#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import json
import urllib.parse
import urllib.request
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


AUTHORIZE_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

# read:recovery / read:cycles -> data we will fetch later
SCOPES = "offline read:recovery read:cycles"

DEFAULT_REDIRECT_URI = "http://localhost:8000/callback"

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / "data" / "processed" / "tokens.json"
ENV_PATH = ROOT / ".env"

# load WHOOP client info
def load_dotenv(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"No .env file at {path}")

    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)

# check for WHOOP client info
def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name} in .env")
    return value

# return client ID
def client_id() -> str:
    return require_env("WHOOP_CLIENT_ID")

# return client secret
def client_secret() -> str:
    return require_env("WHOOP_CLIENT_SECRET")

# redirect url
def redirect_uri() -> str:
    return os.environ.get("WHOOP_REDIRECT_URI", DEFAULT_REDIRECT_URI).strip()

# create URL using client info to allow WHOOP connection
def build_authorize_url(state: str) -> str:
    query = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"

# POST request to WHOOP -> returns access token and refresh tokens
def post_token(form: dict) -> dict:
    body = urllib.parse.urlencode(form).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "whoop-demand/0.1",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Token request failed ({exc.code}): {detail}") from exc

    if "access_token" not in payload:
        raise SystemExit(f"Unexpected token response: {payload}")
    return payload

# sends auth code to WHOOP -> calls on post_token
def exchange_code(code: str) -> dict:
    return post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(),
            "client_id": client_id(),
            "client_secret": client_secret(),
        }
    )

# saves tokens and expiration
def save_tokens(token_payload: dict) -> Path:
    """Write tokens.json. Add expires_at so we can refresh later."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    expires_in = int(token_payload.get("expires_in", 3600))
    stored = {
        "access_token": token_payload["access_token"],
        "refresh_token": token_payload.get("refresh_token"),
        "token_type": token_payload.get("token_type", "bearer"),
        "scope": token_payload.get("scope"),
        "expires_in": expires_in,
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat(),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    TOKEN_PATH.write_text(json.dumps(stored, indent=2) + "\n")
    return TOKEN_PATH

# request to refresh token after expiry
def refresh_tokens(refresh_token: str) -> dict:
    return post_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "scope": "offline",
        }
    )

def load_tokens() -> dict:
    if not TOKEN_PATH.exists():
        raise SystemExit(f"No tokens at {TOKEN_PATH}. Run: python3 src/whoop_auth.py")
    return json.loads(TOKEN_PATH.read_text())

# token expiration check 
def token_is_expired(tokens: dict, skew_seconds: int = 60) -> bool:
    expires_at = tokens.get("expires_at")
    if not expires_at:
        return True
    expiry = datetime.fromisoformat(expires_at)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) + timedelta(seconds=skew_seconds) >= expiry

# retreive valid token 
def get_valid_access_token() -> str:
    load_dotenv(ENV_PATH)
    tokens = load_tokens()
    if token_is_expired(tokens):
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise SystemExit("Access token expired and no refresh_token is saved.")
        print("Access token expired. Refreshing...")
        save_tokens(refresh_tokens(refresh))
        tokens = load_tokens()
    return tokens["access_token"]

# handle GET callback and store auth code + state in class
class CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        expected_path = urllib.parse.urlparse(redirect_uri()).path
        if parsed.path != expected_path:
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        CallbackHandler.error = params.get("error", [None])[0]
        CallbackHandler.code = params.get("code", [None])[0]
        CallbackHandler.state = params.get("state", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if CallbackHandler.error:
            html = f"<h1>WHOOP authorization failed</h1><p>{CallbackHandler.error}</p>"
        else:
            html = (
                "<h1>WHOOP authorization complete</h1>"
                "<p>You can close this tab and return to the terminal.</p>"
            )
        self.wfile.write(html.encode("utf-8"))


# parse callback URL -> auth code + state placed in a CallbackHandler object -> returns auth code
def wait_for_callback(expected_state: str, timeout_seconds: int = 180) -> str:
    parsed = urllib.parse.urlparse(redirect_uri())
    host = parsed.hostname or "localhost"
    port = parsed.port or 80

    server = HTTPServer((host, port), CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print(f"Listening for WHOOP redirect on {redirect_uri()}")
    deadline = time.time() + timeout_seconds
    while thread.is_alive() and time.time() < deadline:
        time.sleep(0.1)

    server.server_close()

    if CallbackHandler.error:
        raise SystemExit(f"WHOOP returned an error: {CallbackHandler.error}")
    if not CallbackHandler.code:
        raise SystemExit("Timed out waiting for the browser callback.")
    if CallbackHandler.state != expected_state:
        raise SystemExit("State mismatch. Refusing to exchange the code.")
    return CallbackHandler.code

# login actions
def login() -> Path:
    load_dotenv(ENV_PATH) # load WHOOP client info 
    state = secrets.token_urlsafe(16) # assign a state
    url = build_authorize_url(state) # build URL with assigned state

    print("Opening WHOOP authorization page...")
    print(url)
    webbrowser.open(url) # open browser

    code = wait_for_callback(expected_state=state) # auth code + state check
    tokens = exchange_code(code) # use auth code to get access + refresh tokens 
    path = save_tokens(tokens) # save tokens

    print(f"Saved tokens to {path}")
    print(f"access_token expires in {tokens.get('expires_in', '?')} seconds")
    if not tokens.get("refresh_token"):
        print("Warning: no refresh_token. Check that the offline scope is enabled.")
    return path


if __name__ == "__main__":
    login()