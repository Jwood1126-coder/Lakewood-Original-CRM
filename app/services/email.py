"""SMTP sender for notifications-to-self only.

Provider-agnostic — pick host/port via env vars. Defaults to Outlook.com
personal (smtp-mail.outlook.com:587 with STARTTLS).

Common providers:
  Outlook.com personal:  SMTP_HOST=smtp-mail.outlook.com   SMTP_PORT=587  TLS
  Microsoft 365:         SMTP_HOST=smtp.office365.com      SMTP_PORT=587  TLS
                         (admin must allow SMTP AUTH for the mailbox)
  Gmail:                 SMTP_HOST=smtp.gmail.com          SMTP_PORT=465  SSL
                         (set SMTP_USE_TLS=0 for SSL on 465; or SMTP_PORT=587 for TLS)
  Yahoo:                 SMTP_HOST=smtp.mail.yahoo.com     SMTP_PORT=587  TLS
  iCloud:                SMTP_HOST=smtp.mail.me.com        SMTP_PORT=587  TLS

Most providers require an "App Password" if 2FA is on:
  Outlook.com:    account.live.com -> Security -> Advanced -> App passwords
  Microsoft 365:  myaccount.microsoft.com -> Security -> App passwords
                  (only if your tenant admin has enabled this)
  Gmail:          myaccount.google.com -> Security -> 2-Step Verification -> App passwords

Why we never email customers from this: deliverability for outbound
self-hosted email to strangers is a swamp (SPF/DKIM/DMARC, IP reputation).
Operator-only notifications side-step that entirely.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from flask import current_app


def _parse_recipients(to: str | list[str]) -> list[str]:
    """Accept a single string ('a@x', 'a@x, b@y') or a list. Return clean list."""
    if isinstance(to, str):
        parts = [t.strip() for t in to.replace(";", ",").split(",")]
    else:
        parts = [str(t).strip() for t in to]
    return [t for t in parts if t]


def send_email(to: str | list[str], subject: str, html: str,
                text: str | None = None) -> None:
    user = current_app.config.get("SMTP_USER")
    password = current_app.config.get("SMTP_PASSWORD")
    host = current_app.config.get("SMTP_HOST", "smtp-mail.outlook.com")
    port = int(current_app.config.get("SMTP_PORT", 587))
    use_tls = bool(current_app.config.get("SMTP_USE_TLS", True))

    if not user or not password:
        raise RuntimeError(
            "SMTP not configured. Set SMTP_USER + SMTP_PASSWORD env vars. "
            "For Outlook.com: generate at "
            "account.live.com -> Security -> App passwords. "
            "For Gmail: myaccount.google.com -> App passwords. "
            "Defaults: SMTP_HOST=smtp-mail.outlook.com, SMTP_PORT=587, SMTP_USE_TLS=1."
        )

    recipients = _parse_recipients(to)
    if not recipients:
        raise ValueError("No valid recipients")

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text or _strip_html(html))
    msg.add_alternative(html, subtype="html")

    if use_tls:
        # Standard pattern for port 587: connect, EHLO, STARTTLS, EHLO, login
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg, to_addrs=recipients)
    else:
        # Implicit SSL (port 465 — Gmail's preferred mode, etc.)
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg, to_addrs=recipients)

    current_app.logger.info("Email sent to %d recipient(s) via %s: %s",
                            len(recipients), host, subject)


def _strip_html(html: str) -> str:
    """Cheap fallback plain-text version. Good enough for transactional notices."""
    import re
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()
