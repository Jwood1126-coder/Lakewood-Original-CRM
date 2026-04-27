"""Gmail SMTP email sender (notifications-to-self only).

Uses smtplib over SSL on port 465 with a Gmail App Password.

Why Gmail: it's what the operator already uses, deliverability is perfect,
and it's free. We never send to customers from this — customer comms always
go through the operator's own Gmail compose window via mailto: links.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from flask import current_app


def send_email(to: str, subject: str, html: str, text: str | None = None) -> None:
    user = current_app.config.get("GMAIL_USER")
    password = current_app.config.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        raise RuntimeError(
            "Gmail SMTP not configured. Set GMAIL_USER and GMAIL_APP_PASSWORD env vars. "
            "Generate the App Password at: myaccount.google.com → Security → "
            "2-Step Verification → App passwords."
        )

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text or _strip_html(html))
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    current_app.logger.info("Email sent to %s: %s", to, subject)


def _strip_html(html: str) -> str:
    """Cheap fallback plain-text version. Good enough for transactional notices."""
    import re
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()
