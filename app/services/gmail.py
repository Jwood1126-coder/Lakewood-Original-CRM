"""Gmail API integration — OAuth + REST helpers.

Mirrors the Jobber pattern (app/services/jobber.py): OAuth dance, token
encrypted in the Setting key/value table via Fernet/HKDF, automatic
refresh before each call.

Docs: https://developers.google.com/gmail/api/v1/reference

Phase 1 scope:
  - readonly access (no send)
  - list message IDs newer than N days
  - get a message's metadata + plain-text body

Why hand-rolled instead of google-api-python-client: matches Jobber's
existing minimal-deps pattern, no extra requirements pin, and we use
~20 lines of REST surface so a 100KB SDK is overkill.
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from typing import Any

import requests
from flask import current_app, url_for

from app.models.setting import get_setting, set_setting
from app.utils.crypto import decrypt_str, encrypt_str

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# readonly is enough for ingestion. userinfo.email tells us whose mailbox
# we're connected to so the settings page can display it.
SCOPES = " ".join([
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
])

_TOKEN_KEY = "gmail_oauth_token_encrypted"


# ---------- token persistence ----------

def _save_token(token_response: dict) -> None:
    blob = dict(token_response)
    if "expires_in" in blob:
        blob["expires_at"] = int(time.time()) + int(blob["expires_in"]) - 30
    set_setting(_TOKEN_KEY, encrypt_str(json.dumps(blob)))


def _load_token() -> dict | None:
    raw = get_setting(_TOKEN_KEY)
    if not raw:
        return None
    try:
        return json.loads(decrypt_str(raw))
    except Exception as e:
        current_app.logger.warning("Could not decrypt Gmail token: %s", e)
        return None


def is_connected() -> bool:
    return _load_token() is not None


def disconnect() -> None:
    set_setting(_TOKEN_KEY, "")


def connected_email() -> str | None:
    """The email address Gmail told us this token belongs to (set during
    callback). Useful for the settings page."""
    tok = _load_token() or {}
    return tok.get("email")


# ---------- OAuth dance ----------

def _redirect_uri() -> str:
    override = current_app.config.get("GMAIL_REDIRECT_URI")
    if override:
        return override
    return url_for("gmail.callback", _external=True)


def build_authorize_url(state: str) -> str:
    cid = current_app.config.get("GMAIL_CLIENT_ID")
    if not cid:
        raise RuntimeError("GMAIL_CLIENT_ID is not set")
    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": _redirect_uri(),
        "scope": SCOPES,
        "state": state,
        # offline gets us a refresh_token; consent forces re-prompt so
        # repeated connect/disconnect cycles always yield a refresh_token
        # (Google omits it on subsequent grants by default).
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    qs = "&".join(f"{k}={requests.utils.quote(v, safe='')}" for k, v in params.items())
    return f"{AUTH_URL}?{qs}"


def exchange_code_for_token(code: str) -> dict:
    cid = current_app.config.get("GMAIL_CLIENT_ID")
    secret = current_app.config.get("GMAIL_CLIENT_SECRET")
    if not (cid and secret):
        raise RuntimeError("GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET not set")
    r = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(),
        "client_id": cid,
        "client_secret": secret,
    }, timeout=30)
    r.raise_for_status()
    tok = r.json()

    # Stamp which Gmail account this is for the settings page display.
    try:
        ui = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {tok['access_token']}"},
            timeout=15,
        )
        if ui.ok:
            tok["email"] = (ui.json() or {}).get("email")
    except Exception:
        pass  # non-fatal; sync still works without the display name

    _save_token(tok)
    return tok


def _refresh_if_needed(tok: dict) -> dict:
    exp = tok.get("expires_at")
    if exp and exp > int(time.time()) + 60:
        return tok
    refresh = tok.get("refresh_token")
    if not refresh:
        return tok  # will fail on next API call; operator must reconnect
    cid = current_app.config["GMAIL_CLIENT_ID"]
    secret = current_app.config["GMAIL_CLIENT_SECRET"]
    r = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": cid,
        "client_secret": secret,
    }, timeout=30)
    r.raise_for_status()
    new_tok = r.json()
    # Google often omits refresh_token on refresh; preserve the original.
    if "refresh_token" not in new_tok and refresh:
        new_tok["refresh_token"] = refresh
    # Preserve the email stamp across refreshes too.
    if tok.get("email"):
        new_tok["email"] = tok["email"]
    _save_token(new_tok)
    return _load_token() or new_tok


# ---------- API client ----------

def _api(method: str, path: str, **kwargs) -> Any:
    """Authenticated request to the Gmail REST API.

    `path` is relative to API_BASE (e.g. '/messages'). Returns parsed JSON
    on 2xx, raises on anything else with the response body in the message
    so the operator sees a useful error in the flash.
    """
    tok = _load_token()
    if not tok:
        raise RuntimeError("Gmail not connected — go to Settings → Gmail.")
    tok = _refresh_if_needed(tok)
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {tok['access_token']}"
    url = API_BASE + path
    r = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    if not r.ok:
        snippet = r.text[:300] if r.text else ""
        raise RuntimeError(f"Gmail API {r.status_code}: {snippet}")
    return r.json() if r.text else {}


def list_message_ids(*, days_back: int = 14, max_results: int = 100,
                      page_token: str | None = None) -> dict:
    """Return {'messages': [{'id', 'threadId'}, ...], 'nextPageToken': ...}.

    Uses Gmail's `q=newer_than:<N>d` so we don't refetch ancient mail on
    first connect. Caller paginates via nextPageToken.
    """
    params = {
        "q": f"newer_than:{days_back}d",
        "maxResults": min(max_results, 500),  # Gmail caps at 500
    }
    if page_token:
        params["pageToken"] = page_token
    return _api("GET", "/messages", params=params)


def get_message(msg_id: str, *, format: str = "metadata",
                 metadata_headers: tuple[str, ...] = ("From", "Subject", "Date", "To")
                 ) -> dict:
    """Fetch a single message. format='metadata' is cheaper than 'full'
    and gives us the headers we need for Phase 1 (Subject/From/Date).

    Use format='full' later when we want body parsing for Voice/voicemail."""
    params: dict[str, Any] = {"format": format}
    if format == "metadata":
        params["metadataHeaders"] = list(metadata_headers)
    return _api("GET", f"/messages/{msg_id}", params=params)


def decode_body_part(part: dict) -> str:
    """Decode a Gmail message part's body. Gmail base64url-encodes payload
    bodies. Returns empty string if the part has no inline body."""
    body = (part or {}).get("body") or {}
    data = body.get("data")
    if not data:
        return ""
    # Gmail uses URL-safe base64 without padding
    pad = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + pad).decode("utf-8", errors="replace")
    except Exception:
        return ""


def parse_internal_date(ms_str: str | None) -> datetime | None:
    """Gmail's internalDate is epoch milliseconds as a string. Returns
    UTC-naive datetime per project storage convention."""
    if not ms_str:
        return None
    try:
        ms = int(ms_str)
    except (TypeError, ValueError):
        return None
    return datetime.utcfromtimestamp(ms / 1000.0)
