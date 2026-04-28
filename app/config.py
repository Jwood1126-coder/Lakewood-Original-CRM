"""Application configuration loaded from environment.

Single source of truth for runtime config. Read once at startup,
attached to `app.config`. Don't reach into os.environ from anywhere else.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root if present (no-op in production)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required env var: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return val


def _resolve_sqlite_uri(uri: str) -> str:
    """Convert a relative sqlite:/// URI to an absolute one anchored at PROJECT_ROOT.

    Flask-SQLAlchemy treats relative SQLite paths as relative to instance/,
    which surprises everyone. We want them relative to the project root.
    Absolute paths and non-sqlite URIs pass through unchanged.
    """
    prefix = "sqlite:///"
    if not uri.startswith(prefix):
        return uri
    rest = uri[len(prefix):]
    if rest.startswith("/") or (len(rest) > 1 and rest[1] == ":"):
        return uri  # already absolute (POSIX or Windows drive)
    return prefix + str((PROJECT_ROOT / rest).resolve()).replace("\\", "/")


class Config:
    # --- Required ---
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-do-not-use-in-prod"
    SQLALCHEMY_DATABASE_URI = _resolve_sqlite_uri(
        os.environ.get("DATABASE_URL", "sqlite:///./data/app.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        # Connection-level pragmas. WAL mode is set in the connect listener
        # in extensions.py — that's where it has to go for SQLite.
        "pool_pre_ping": True,
    }

    # --- Paths (all under data/ by default) ---
    PHOTO_DIR = Path(os.environ.get("PHOTO_DIR", "./data/photos")).resolve()
    ARCHIVE_DIR = Path(os.environ.get("ARCHIVE_DIR", "./data/archive")).resolve()
    BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "./data/backups")).resolve()

    # --- Admin bootstrap ---
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  # only used on first run

    # --- Business display ---
    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Your Business Name")
    BUSINESS_ADDRESS = os.environ.get(
        "BUSINESS_ADDRESS", "123 Main St, Anytown, OH 44000"
    )
    BUSINESS_PHONE = os.environ.get("BUSINESS_PHONE", "(555) 555-5555")
    BUSINESS_EMAIL = os.environ.get("BUSINESS_EMAIL", "")

    # --- Defaults ---
    DEFAULT_COUNTY = os.environ.get("DEFAULT_COUNTY", "Cuyahoga")
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "America/New_York")

    # --- Sessions ---
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 days
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    # Set SESSION_COOKIE_SECURE = True via env in production (handled below)

    # --- Uploads ---
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB request cap (multi-photo posts)

    # --- Anthropic (Phase 5) ---
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")

    # --- SMTP (notifications-to-self only; never sent to customers) ---
    # Works with any SMTP provider. Defaults match Outlook.com personal.
    # Aliases for backwards compat: GMAIL_USER, GMAIL_APP_PASSWORD.
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp-mail.outlook.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "1") == "1"  # STARTTLS on 587
    SMTP_USER = (
        os.environ.get("SMTP_USER")
        or os.environ.get("GMAIL_USER")          # legacy
    )
    SMTP_PASSWORD = (
        os.environ.get("SMTP_PASSWORD")
        or os.environ.get("GMAIL_APP_PASSWORD")  # legacy
    )
    NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL")

    # --- Backblaze B2 (Phase 1 backups) ---
    B2_ENDPOINT_URL = os.environ.get("B2_ENDPOINT_URL")
    B2_KEY_ID = os.environ.get("B2_KEY_ID")
    B2_APPLICATION_KEY = os.environ.get("B2_APPLICATION_KEY")
    B2_BUCKET = os.environ.get("B2_BUCKET")

    # --- Stripe (Phase 6) ---
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

    # --- Jobber API (one-shot data migration; OAuth flow) ---
    JOBBER_CLIENT_ID = os.environ.get("JOBBER_CLIENT_ID")
    JOBBER_CLIENT_SECRET = os.environ.get("JOBBER_CLIENT_SECRET")
    # Optional override for the OAuth callback URL. Defaults to
    # request.url_root + "/jobber/callback" at runtime if unset.
    JOBBER_REDIRECT_URI = os.environ.get("JOBBER_REDIRECT_URI")
    # Jobber requires this header on every GraphQL call. Pin to a recent
    # stable version; bump as Jobber publishes new ones.
    # Active versions (per Jobber's changelog): 2025-04-16 (latest stable),
    # 2025-01-20, 2024-12-05, 2024-11-12. Older versions auto-deprecate
    # 12 months after a successor releases. Earlier dates (e.g. 2024-04-26)
    # return 404 — they're not in the version registry at all.
    JOBBER_GRAPHQL_VERSION = os.environ.get("JOBBER_GRAPHQL_VERSION", "2025-04-16")

    # --- Behavior flags ---
    DEBUG = _bool("FLASK_DEBUG", default=False)
    TESTING = False

    # In production, force secure cookies. Heuristic: if SECRET_KEY was set
    # explicitly (i.e. not the dev fallback), assume prod-ish.
    SESSION_COOKIE_SECURE = bool(os.environ.get("SECRET_KEY")) and not DEBUG

    @classmethod
    def ensure_dirs(cls) -> None:
        """Make sure runtime directories exist. Called from create_app()."""
        for path in (cls.PHOTO_DIR, cls.ARCHIVE_DIR, cls.BACKUP_DIR):
            path.mkdir(parents=True, exist_ok=True)


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-only"
