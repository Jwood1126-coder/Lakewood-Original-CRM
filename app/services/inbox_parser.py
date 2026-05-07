"""Classify inbound Gmail messages and match them to clients.

Recognized senders:

  Google Voice SMS
    From: "Sender Name" <2165551234@txt.voice.google.com>
    The local part of the address IS the sender's 10-digit phone.

  Google Voice voicemail
    From: "Google Voice" <voice-noreply@google.com>
    Subject: "New voicemail from (216) 555-1234"

  Google Voice missed call
    From: "Google Voice" <voice-noreply@google.com>
    Subject: "Missed call from (216) 555-1234"

  M365-forwarded business mail (when an Outlook redirect rule preserves From)
    From: client@example.com (preserved by redirect, not standard forward)

  Plain forwarded mail (standard forward — original sender hidden)
    From: jakewood@lakewoodoriginal.com
    Body starts with "From: client@example.com..."  (parsed from snippet)

Output: (kind, from_phone, from_email) where any field can be None.

Matching:
  - Email exact match (case-insensitive) → Client.email
  - Phone fuzzy match (last 7 digits) → Client.phone

Stored back on the InboxMessage row as `kind`, `from_phone`, `client_id`.
"""
from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import func, select

from app.extensions import db
from app.models.client import Client
from app.models.inbox_message import InboxMessage
from app.utils.phone import normalize_phone

# Sender patterns
VOICE_SMS_DOMAIN = "txt.voice.google.com"
VOICE_NOTIFY_FROM = "voice-noreply@google.com"

# "(216) 555-1234" or "216-555-1234" or "+1 216 555 1234"
PHONE_RE = re.compile(r"\+?1?[\s.\-(]*\d{3}[\s.\-)]*\d{3}[\s.\-]*\d{4}")
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")


def _phone_from_text(text: str | None) -> str | None:
    if not text:
        return None
    m = PHONE_RE.search(text)
    if not m:
        return None
    return normalize_phone(m.group(0))


def _phone_from_local_part(addr: str | None) -> str | None:
    """The local part of an SMS-via-Voice address is the sender's number."""
    if not addr or "@" not in addr:
        return None
    local = addr.split("@", 1)[0]
    return normalize_phone(local)


def classify(from_addr: str | None,
             subject: str | None,
             snippet: str | None) -> tuple[str, str | None, str | None]:
    """Return (kind, from_phone, original_email) for a Gmail message.

    kind ∈ {'sms', 'voicemail', 'missed_call' (mapped to voicemail), 'email', 'unknown'}
    """
    addr = (from_addr or "").lower()

    # --- Voice SMS ---
    if VOICE_SMS_DOMAIN in addr:
        phone = _phone_from_local_part(addr) or _phone_from_text(subject)
        return "sms", phone, None

    # --- Voice voicemail / missed call ---
    if addr == VOICE_NOTIFY_FROM:
        phone = _phone_from_text(subject) or _phone_from_text(snippet)
        # We collapse "missed call" into voicemail for the kind enum;
        # Phase 1 only allows {email, sms, voicemail, unknown}.
        return "voicemail", phone, None

    # --- Plain forwarded business mail (sender = your own address) ---
    # Heuristic: snippet contains a "From: client@example.com" line, which
    # Outlook prepends when forwarding. Not perfect (any reply with quoted
    # headers can match) but catches the common case until you switch the
    # M365 rule to "redirect".
    if snippet:
        m = re.search(r"\bFrom:\s*([^\s<>]+@[^\s<>]+)", snippet, re.IGNORECASE)
        if m and EMAIL_RE.match(m.group(1)):
            return "email", None, m.group(1).lower()

    # --- Default: ordinary email ---
    if from_addr and EMAIL_RE.match(from_addr):
        return "email", None, from_addr.lower()

    return "unknown", None, None


# ---------- matching ----------

def _client_by_email(email: str) -> Client | None:
    if not email:
        return None
    return db.session.scalar(
        select(Client).where(func.lower(Client.email) == email.lower())
    )


def _client_by_phone_last7(phone_digits: str) -> Client | None:
    """Match on the last 7 digits so different formatting / leading-1
    variations all resolve to the same client."""
    if not phone_digits:
        return None
    last7 = phone_digits[-7:]
    if len(last7) < 7:
        return None
    return db.session.scalar(
        select(Client).where(Client.phone.like(f"%{last7}"))
    )


def match(from_phone: str | None, from_email: str | None) -> Client | None:
    if from_email:
        c = _client_by_email(from_email)
        if c:
            return c
    if from_phone:
        c = _client_by_phone_last7(from_phone)
        if c:
            return c
    return None


# ---------- bulk apply ----------

def apply_to(msgs: Iterable[InboxMessage]) -> dict:
    """Run classify+match on each message in-place. Caller commits.

    Returns counts by outcome so the operator-flash can show what happened.
    """
    out = {"classified_sms": 0, "classified_voicemail": 0,
           "classified_email": 0, "classified_unknown": 0,
           "matched": 0, "unmatched": 0}
    for m in msgs:
        kind, phone, email = classify(m.from_addr, m.subject, m.snippet)
        m.kind = kind if kind != "missed_call" else "voicemail"
        if phone:
            m.from_phone = phone
        # If we extracted an original email from a forwarded message and the
        # stored from_addr is just the forwarder, prefer the original.
        if email and (not m.from_addr or "@" not in (m.from_addr or "")):
            m.from_addr = email[:320]
        elif email and email != (m.from_addr or "").lower():
            # Keep the forwarder visible as from_addr; matching uses the
            # original below regardless.
            pass

        client = match(phone, email or m.from_addr)
        if client:
            m.client_id = client.id
            out["matched"] += 1
        else:
            out["unmatched"] += 1

        if kind == "sms":
            out["classified_sms"] += 1
        elif kind == "voicemail":
            out["classified_voicemail"] += 1
        elif kind == "email":
            out["classified_email"] += 1
        else:
            out["classified_unknown"] += 1
    return out


def backfill_all() -> dict:
    """Re-run classify+match across every InboxMessage row. Safe to run
    multiple times; just overwrites kind/from_phone/client_id with the
    current parser's verdict."""
    msgs = db.session.scalars(select(InboxMessage)).all()
    stats = apply_to(msgs)
    db.session.commit()
    stats["seen"] = len(msgs)
    return stats
