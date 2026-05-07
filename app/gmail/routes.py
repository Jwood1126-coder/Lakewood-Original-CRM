"""Gmail OAuth + sync routes. Mirrors the Jobber blueprint pattern.

GET  /gmail              → status page (connected? + Connect / Sync buttons)
POST /gmail/connect      → kicks off OAuth: generates state, redirects to Google
GET  /gmail/callback     → Google redirects here with ?code=...&state=...
POST /gmail/sync         → pull recent messages, store as InboxMessage rows
POST /gmail/disconnect   → wipes the stored token

State CSRF-protected via session cookie; callback exempted from CSRFProtect
because Google GETs it cross-origin.
"""
from __future__ import annotations

import secrets

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required

from app.extensions import csrf

bp = Blueprint("gmail", __name__, template_folder="../templates/gmail")


@bp.route("/")
@login_required
def index():
    has_creds = bool(
        current_app.config.get("GMAIL_CLIENT_ID")
        and current_app.config.get("GMAIL_CLIENT_SECRET")
    )
    connected = False
    connected_email = None
    import_error = None
    try:
        from app.services.gmail import is_connected, connected_email as _email
        if has_creds:
            connected = is_connected()
            connected_email = _email() if connected else None
    except Exception as e:
        current_app.logger.exception("Gmail service import/check failed")
        import_error = repr(e)

    # Recent message count for at-a-glance status
    recent_count = None
    try:
        from app.extensions import db
        from app.models.inbox_message import InboxMessage
        from sqlalchemy import func, select
        recent_count = db.session.scalar(
            select(func.count(InboxMessage.id)).where(InboxMessage.source == "gmail")
        ) or 0
    except Exception:
        pass

    return render_template(
        "gmail/index.html",
        has_creds=has_creds,
        connected=connected,
        connected_email=connected_email,
        recent_count=recent_count,
        import_error=import_error,
    )


@bp.route("/connect", methods=["POST"])
@login_required
def connect():
    from app.services.gmail import build_authorize_url
    if not current_app.config.get("GMAIL_CLIENT_ID"):
        flash("GMAIL_CLIENT_ID env var is not set.", "error")
        return redirect(url_for("gmail.index"))
    state = secrets.token_urlsafe(24)
    session["gmail_oauth_state"] = state
    return redirect(build_authorize_url(state))


@bp.route("/callback")
@csrf.exempt
def callback():
    """Google redirects here after authorization. NOT login_required —
    operator is mid-redirect back to our site. We verify the state token
    from session matches what we stored at /connect time."""
    code = request.args.get("code")
    state = request.args.get("state")
    expected = session.pop("gmail_oauth_state", None)
    err = request.args.get("error")

    if err:
        flash(f"Google declined the connection: {err}", "error")
        return redirect(url_for("gmail.index"))

    if not code or not state or state != expected:
        flash("OAuth state mismatch — try connecting again.", "error")
        return redirect(url_for("gmail.index"))

    try:
        from app.services.gmail import exchange_code_for_token
        exchange_code_for_token(code)
    except Exception as e:
        current_app.logger.exception("Gmail token exchange failed")
        flash(f"Couldn't complete Gmail connection: {e}", "error")
        return redirect(url_for("gmail.index"))

    flash("Connected to Gmail. Hit 'Sync now' to pull recent messages.", "success")
    return redirect(url_for("gmail.index"))


@bp.route("/sync", methods=["POST"])
@login_required
def sync():
    from app.services.gmail_sync import sync_recent
    days = request.form.get("days_back", "14")
    try:
        days_back = max(1, min(60, int(days)))
    except (TypeError, ValueError):
        days_back = 14
    try:
        s = sync_recent(days_back=days_back, max_messages=200)
    except Exception as e:
        current_app.logger.exception("Gmail sync failed")
        flash(f"Sync failed: {e}", "error")
        return redirect(url_for("gmail.index"))
    msg = (f"Gmail sync ({days_back}d): {s['seen']} seen → "
           f"{s['created']} new, {s['skipped_existing']} already imported.")
    if s["errors"]:
        msg += f" {len(s['errors'])} errors (check logs)."
    flash(msg, "success" if not s["errors"] else "warning")
    return redirect(url_for("main.messages"))


@bp.route("/disconnect", methods=["POST"])
@login_required
def disconnect():
    from app.services.gmail import disconnect as _disconnect
    _disconnect()
    flash("Disconnected from Gmail. Stored messages are kept; reconnect anytime.", "info")
    return redirect(url_for("gmail.index"))


@bp.route("/reclassify", methods=["POST"])
@login_required
def reclassify():
    """Re-run the parser + client matcher across every stored message.
    Useful after the parser is updated, after new clients are added (so
    previously-unmatched messages can find them), or after switching
    M365 forwarding to redirect."""
    from app.services.inbox_parser import backfill_all
    try:
        s = backfill_all()
    except Exception as e:
        current_app.logger.exception("Reclassify failed")
        flash(f"Reclassify failed: {e}", "error")
        return redirect(url_for("gmail.index"))
    msg = (f"Re-classified {s['seen']} messages: "
           f"{s['matched']} matched a client, {s['unmatched']} unmatched. "
           f"({s['classified_sms']} SMS, {s['classified_voicemail']} voicemail, "
           f"{s['classified_email']} email, {s['classified_unknown']} unknown.)")
    flash(msg, "success")
    return redirect(url_for("gmail.index"))
