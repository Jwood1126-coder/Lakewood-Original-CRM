"""Singleton key-value Settings table.

Stores user-editable configuration that doesn't fit elsewhere — currently
business profile fields (name, address, phone, email). Reads fall back to
the env-driven Config defaults if a key isn't set.
"""
from __future__ import annotations

from datetime import datetime

from flask import current_app
from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Setting(db.Model):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


# --- helper API ---

# Map of setting key -> Flask config key used as fallback
_FALLBACKS = {
    "business_name":    "BUSINESS_NAME",
    "business_address": "BUSINESS_ADDRESS",
    "business_phone":   "BUSINESS_PHONE",
    "business_email":   "BUSINESS_EMAIL",
}


def get_setting(key: str, default: str | None = None) -> str | None:
    s = db.session.get(Setting, key)
    if s and s.value is not None:
        return s.value
    fallback_key = _FALLBACKS.get(key)
    if fallback_key:
        return current_app.config.get(fallback_key) or default
    return default


def set_setting(key: str, value: str | None) -> None:
    s = db.session.get(Setting, key)
    if s is None:
        s = Setting(key=key, value=value)
        db.session.add(s)
    else:
        s.value = value
    db.session.commit()


def all_business_settings() -> dict:
    return {
        "name":    get_setting("business_name", ""),
        "address": get_setting("business_address", ""),
        "phone":   get_setting("business_phone", ""),
        "email":   get_setting("business_email", ""),
    }
