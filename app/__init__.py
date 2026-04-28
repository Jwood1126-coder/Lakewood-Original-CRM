"""Flask application factory."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask

from app.config import Config, TestConfig
from app.extensions import (
    csrf,
    db,
    init_login_manager,
    limiter,
    login_manager,
    migrate,
)


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    if not app.config["TESTING"]:
        config_class.ensure_dirs()

    _configure_logging(app)
    _init_extensions(app)
    _init_audit(app)
    _register_blueprints(app)
    _register_context(app)
    _register_error_handlers(app)
    _start_scheduler(app)

    return app


def _init_audit(app: Flask) -> None:
    """Wire automatic audit logging to the SQLAlchemy session."""
    from app.extensions import db
    from app.services.audit import init_audit, register_session_events
    init_audit(app)
    # Flask-SQLAlchemy 3.x exposes the scoped session via db.session,
    # but we attach to the underlying Session class so all sessions are covered.
    register_session_events(db.session)


def _start_scheduler(app: Flask) -> None:
    """Start APScheduler unless we're testing or it's explicitly disabled."""
    from app.services.scheduler import init_scheduler
    init_scheduler(app)


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    init_login_manager(app)
    csrf.init_app(app)
    # Disable the rate limiter in TESTING so tests don't get throttled
    if app.config.get("TESTING"):
        limiter.enabled = False
    limiter.init_app(app)


def _register_blueprints(app: Flask) -> None:
    from app.assistant.routes import bp as assistant_bp
    from app.auth.routes import bp as auth_bp
    from app.clients.routes import bp as clients_bp
    from app.intake.routes import bp as intake_bp
    from app.invoices.routes import bp as invoices_bp
    from app.jobs.routes import bp as jobs_bp
    from app.main.routes import bp as main_bp
    from app.properties.routes import bp as properties_bp
    from app.quotes.routes import bp as quotes_bp
    from app.reports.routes import bp as reports_bp
    from app.settings.routes import bp as settings_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(clients_bp, url_prefix="/clients")
    app.register_blueprint(properties_bp, url_prefix="/properties")
    app.register_blueprint(jobs_bp, url_prefix="/jobs")
    app.register_blueprint(quotes_bp, url_prefix="/quotes")
    app.register_blueprint(invoices_bp, url_prefix="/invoices")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(assistant_bp, url_prefix="/assistant")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(intake_bp, url_prefix="/intake")


def _register_context(app: Flask) -> None:
    from flask_login import current_user

    @app.context_processor
    def inject_globals():
        # Lazy imports to avoid circulars at module load
        from sqlalchemy import func, select
        from app.extensions import db
        from app.models.notification import Notification
        from app.models.setting import get_setting

        theme = "dark"
        try:
            if current_user.is_authenticated:
                theme = current_user.theme or "dark"
        except Exception:
            pass

        try:
            business_name = get_setting("business_name") or app.config["BUSINESS_NAME"]
        except Exception:
            business_name = app.config["BUSINESS_NAME"]

        unread = 0
        try:
            if current_user.is_authenticated:
                unread = db.session.scalar(
                    select(func.count(Notification.id))
                    .where(Notification.read_at.is_(None))
                ) or 0
        except Exception:
            pass

        return {
            "business_name": business_name,
            "app_theme": theme,
            "unread_count": unread,
        }


def _register_error_handlers(app: Flask) -> None:
    from flask import render_template

    @app.errorhandler(404)
    def not_found(_):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template("errors/500.html"), 500

    @app.errorhandler(429)
    def too_many_requests(_):
        return render_template("errors/429.html"), 429


def _configure_logging(app: Flask) -> None:
    if app.config["TESTING"]:
        return

    log_dir = Path(app.config.get("LOG_DIR", "./data/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
    )
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info("Handyman CRM starting up")
