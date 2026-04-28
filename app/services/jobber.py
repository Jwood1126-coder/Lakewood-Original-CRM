"""Jobber API integration — OAuth + GraphQL.

Used for one-shot data migration from Jobber. Tokens stored encrypted
in the Setting key-value table (see app/utils/crypto.py).

Usage flow:
1. Operator hits /jobber/connect
2. Redirected to Jobber's authorize page with state token
3. After consent, Jobber redirects back to /jobber/callback?code=...
4. We exchange the code for access + refresh tokens, encrypt + store.
5. Settings → Jobber → "Pull data" runs sync_clients() etc., which
   pages through GraphQL queries and feeds rows into the same
   ingestion pipeline the CSV importer uses.

Refresh: Jobber access tokens last ~1 hour. Before each request we check
expiry and refresh if needed. (Migration is a one-time thing so this
is mostly precautionary.)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import requests
from flask import current_app, request, url_for

from app.extensions import db
from app.models.setting import get_setting, set_setting
from app.utils.crypto import decrypt_str, encrypt_str

AUTH_URL = "https://api.getjobber.com/api/oauth/authorize"
TOKEN_URL = "https://api.getjobber.com/api/oauth/token"
GRAPH_URL = "https://api.getjobber.com/api/graphql"

SCOPES = "read_clients read_jobs read_quotes read_invoices"

_TOKEN_KEY = "jobber_oauth_token_encrypted"


# ---------- token persistence ----------

def _save_token(token_response: dict) -> None:
    """Encrypt + persist the OAuth response. Includes computed expires_at."""
    blob = dict(token_response)
    if "expires_in" in blob:
        # Store absolute expiry (epoch seconds) for easier comparison
        blob["expires_at"] = int(time.time()) + int(blob["expires_in"]) - 30
    set_setting(_TOKEN_KEY, encrypt_str(json.dumps(blob)))


def _load_token() -> dict | None:
    raw = get_setting(_TOKEN_KEY)
    if not raw:
        return None
    try:
        return json.loads(decrypt_str(raw))
    except Exception as e:
        current_app.logger.warning("Could not decrypt Jobber token: %s", e)
        return None


def is_connected() -> bool:
    return _load_token() is not None


def disconnect() -> None:
    set_setting(_TOKEN_KEY, "")


# ---------- OAuth dance ----------

def _redirect_uri() -> str:
    """Use configured override or derive from current request."""
    override = current_app.config.get("JOBBER_REDIRECT_URI")
    if override:
        return override
    return url_for("jobber.callback", _external=True)


def build_authorize_url(state: str) -> str:
    cid = current_app.config.get("JOBBER_CLIENT_ID")
    if not cid:
        raise RuntimeError("JOBBER_CLIENT_ID is not set")
    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": _redirect_uri(),
        "scope": SCOPES,
        "state": state,
    }
    qs = "&".join(f"{k}={requests.utils.quote(v, safe='')}" for k, v in params.items())
    return f"{AUTH_URL}?{qs}"


def exchange_code_for_token(code: str) -> dict:
    cid = current_app.config.get("JOBBER_CLIENT_ID")
    secret = current_app.config.get("JOBBER_CLIENT_SECRET")
    if not (cid and secret):
        raise RuntimeError("JOBBER_CLIENT_ID / JOBBER_CLIENT_SECRET not set")
    r = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(),
        "client_id": cid,
        "client_secret": secret,
    }, timeout=30)
    r.raise_for_status()
    tok = r.json()
    _save_token(tok)
    return tok


def _refresh_if_needed(tok: dict) -> dict:
    """Refresh the token if it's within 60 seconds of expiry."""
    exp = tok.get("expires_at")
    if exp and exp > int(time.time()) + 60:
        return tok
    refresh = tok.get("refresh_token")
    if not refresh:
        return tok  # nothing to do; will fail on next API call
    cid = current_app.config["JOBBER_CLIENT_ID"]
    secret = current_app.config["JOBBER_CLIENT_SECRET"]
    r = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": cid,
        "client_secret": secret,
    }, timeout=30)
    r.raise_for_status()
    new_tok = r.json()
    # Some providers don't return a new refresh_token; preserve the old one
    if "refresh_token" not in new_tok and refresh:
        new_tok["refresh_token"] = refresh
    _save_token(new_tok)
    return _load_token() or new_tok


# ---------- GraphQL client ----------

def graphql(query: str, variables: dict | None = None,
             max_retries: int = 10) -> dict:
    """POST a GraphQL query. Auto-retries on Jobber's THROTTLED error
    with exponential backoff (15s, 30s, 60s, then 90s × 7 more).

    Also sleeps 1.5s BEFORE every call to stay under Jobber's effective
    rate limit (which is much tighter than their documented 2500 pts/min
    for our app size).
    """
    tok = _load_token()
    if not tok:
        raise RuntimeError("Jobber not connected — go to Settings → Jobber sync.")
    tok = _refresh_if_needed(tok)
    headers = {
        "Authorization": f"Bearer {tok['access_token']}",
        "Content-Type": "application/json",
        "X-JOBBER-GRAPHQL-VERSION": current_app.config.get(
            "JOBBER_GRAPHQL_VERSION", "2025-04-16"
        ),
    }

    # Pre-call throttle: even for tiny apps Jobber's effective limit
    # appears to be much tighter than the documented 2500 pts/min.
    # 1.5s pre-sleep keeps sustained rate at ~40 req/min — empirically
    # safe across long syncs.
    time.sleep(1.5)

    backoff = 15.0
    for attempt in range(max_retries):
        r = requests.post(GRAPH_URL,
                          json={"query": query, "variables": variables or {}},
                          headers=headers, timeout=60)
        # If Jobber returned 429, honor Retry-After header before parsing body
        if r.status_code == 429:
            retry_after = float(r.headers.get("Retry-After", str(backoff)))
            current_app.logger.info(
                "Jobber HTTP 429, sleeping %.1fs (attempt %d/%d)",
                retry_after, attempt + 1, max_retries,
            )
            time.sleep(retry_after)
            backoff = min(backoff * 2, 90)
            continue
        r.raise_for_status()
        body = r.json()
        errs = body.get("errors") or []
        is_throttled = any(
            (e.get("extensions") or {}).get("code") == "THROTTLED"
            or "throttled" in (e.get("message") or "").lower()
            for e in errs
        )
        if is_throttled and attempt < max_retries - 1:
            current_app.logger.info(
                "Jobber THROTTLED, sleeping %.1fs (attempt %d/%d)",
                backoff, attempt + 1, max_retries,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 90)
            continue
        if errs:
            raise RuntimeError(f"Jobber GraphQL error: {errs}")
        return body.get("data") or {}

    raise RuntimeError("Jobber GraphQL: exhausted retries (rate-limited)")


# ---------- sync helpers ----------

def fetch_all_clients(page_size: int = 50) -> list[dict]:
    """Page through all clients via GraphQL, returning a flat list of dicts.

    Each dict shape mirrors what the CSV importer expects after parsing
    (so we can reuse write_clients()):

        {
          "jobber_client_id": str,
          "name": str,
          "phone": str | None,
          "email": str | None,
          "is_company": bool,
          "company_name": str,
          "contact_first": str,
          "contact_last": str,
          "lead_source": str,
          "referred_by": str,
          "created_at": datetime | None,
          "properties": [
              {"label", "address_line1", "address_line2", "city",
               "state", "zip_code", "county", "tax_rate"}
          ],
        }
    """
    from decimal import Decimal
    from app.utils.ohio_tax import lookup_county, lookup_rate
    from app.utils.phone import normalize_phone

    # Client.properties is a plain [Property!] (NOT a Relay connection),
    # so query its fields directly — no `nodes { ... }` wrapper.
    QUERY = """
    query Clients($first: Int!, $after: String) {
      clients(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id
            firstName
            lastName
            companyName
            isCompany
            createdAt
            phones { number primary }
            emails { address primary }
            properties {
              id
              address {
                street1
                street2
                city
                province
                postalCode
                country
              }
            }
          }
        }
      }
    }
    """

    out: list[dict] = []
    after = None
    while True:
        data = graphql(QUERY, {"first": page_size, "after": after})
        connection = data.get("clients") or {}
        for edge in connection.get("edges") or []:
            node = edge["node"]

            # Pick best phone / email
            phones = node.get("phones") or []
            phone_raw = next(
                (p["number"] for p in phones if p.get("primary")),
                phones[0]["number"] if phones else None,
            )
            phone = normalize_phone(phone_raw) if phone_raw else None
            emails = node.get("emails") or []
            email = next(
                (e["address"] for e in emails if e.get("primary")),
                emails[0]["address"] if emails else None,
            )
            if email:
                email = email.lower()

            display = (node.get("companyName") or "").strip() or " ".join(
                filter(None, [node.get("firstName"), node.get("lastName")])
            ).strip() or f"Unnamed (Jobber #{node['id']})"

            # Properties — Client.properties is [Property!] (plain list)
            props = []
            for prop_node in (node.get("properties") or []):
                addr = prop_node.get("address") or {}
                street1 = (addr.get("street1") or "").strip()
                if not street1:
                    continue
                zip_code = (addr.get("postalCode") or "").strip()[:10]
                county = lookup_county(zip_code)
                props.append({
                    "jobber_property_id": prop_node.get("id"),
                    "label": "Home" if len(props) == 0 else f"Property #{len(props)+1}",
                    "address_line1": street1,
                    "address_line2": (addr.get("street2") or "").strip(),
                    "city": (addr.get("city") or "Unknown").strip(),
                    "state": (addr.get("province") or "OH").strip()[:2].upper() or "OH",
                    "zip_code": zip_code or "00000",
                    "county": county,
                    "tax_rate": Decimal(str(lookup_rate(county))),
                })

            created_raw = node.get("createdAt")
            created_at = None
            if created_raw:
                try:
                    created_at = datetime.fromisoformat(
                        created_raw.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            out.append({
                "jobber_client_id": node["id"],
                "name": display,
                "phone": phone,
                "email": email,
                "is_company": bool(node.get("isCompany")),
                "company_name": (node.get("companyName") or "").strip(),
                "contact_first": (node.get("firstName") or "").strip(),
                "contact_last": (node.get("lastName") or "").strip(),
                "lead_source": "",
                "referred_by": "",
                "created_at": created_at,
                "properties": props,
            })

        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor")

    return out
