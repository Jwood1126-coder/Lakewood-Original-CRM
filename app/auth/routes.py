"""Auth routes — login, logout, change password."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from app.auth.forms import ChangePasswordForm, LoginForm
from app.extensions import db, limiter
from app.models.user import User

bp = Blueprint("auth", __name__, template_folder="../templates/auth")


def _is_safe_url(target: str) -> bool:
    """Reject open redirects: only allow same-host URLs."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    return (
        test_url.scheme in ("http", "https", "")
        and (test_url.netloc == "" or ref_url.netloc == test_url.netloc)
    )


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("8 per minute; 30 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            select(User).where(User.email == form.email.data.strip().lower())
        )
        if user and user.verify_password(form.password.data):
            login_user(user, remember=form.remember.data)
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            current_app.logger.info("Login: %s", user.email)

            next_page = request.args.get("next")
            if next_page and _is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for("main.index"))

        flash("Invalid email or password.", "error")
        current_app.logger.warning("Failed login attempt for %s", form.email.data)

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You've been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.verify_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
        elif form.new_password.data != form.confirm_password.data:
            flash("New passwords don't match.", "error")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("main.index"))

    return render_template("auth/change_password.html", form=form)
