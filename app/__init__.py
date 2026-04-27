"""Flask application factory."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask

from app.config import Config, TestConfig
from app.extensions import csrf, db, init_login_manager, login_manager, migrate


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
    _register_blueprints(app)
    _register_context(app)
    _register_error_handlers(app)
    _start_scheduler(app)

    return app


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


def _register_blueprints(app: Flask) -> None:
    from app.auth.routes import bp as auth_bp
    from app.clients.routes import bp as clients_bp
    from app.jobs.routes import bp as jobs_bp
    from app.main.routes import bp as main_bp
    from app.properties.routes import bp as properties_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(clients_bp, url_prefix="/clients")
    app.register_blueprint(properties_bp, url_prefix="/properties")
    app.register_blueprint(jobs_bp, url_prefix="/jobs")


def _register_context(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        return {
            "business_name": app.config["BUSINESS_NAME"],
        }


def _register_error_handlers(app: Flask) -> None:
    from flask import render_template

    @app.errorhandler(404)
    def not_found(_):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template("errors/500.html"), 500


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
