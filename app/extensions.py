"""Flask extensions, instantiated unbound at import time.

Each extension is `init_app()`-ed inside create_app(). Centralizing them
here avoids circular imports and lets tests use the same instances.
"""
from __future__ import annotations

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


# Apply SQLite pragmas (WAL, foreign keys) on every new connection.
# This is the canonical way to set per-connection settings in SQLAlchemy.
@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: D401
    # Only act on SQLite. Postgres connections won't have this method.
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception:
        # Non-SQLite drivers raise here; ignore.
        pass


def init_login_manager(app) -> None:
    """Wire up Flask-Login user loader and login view."""
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"
    login_manager.session_protection = "strong"

    from app.models.user import User  # local import avoids circular

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))
