"""Jobber OAuth + sync routes.

GET  /jobber                  → status page (connected? + Connect / Sync buttons)
POST /jobber/connect          → kicks off OAuth: generates state, redirects to Jobber
GET  /jobber/callback         → Jobber redirects here with ?code=...&state=...
POST /jobber/sync/clients     → pull all clients via GraphQL → import via existing pipeline
POST /jobber/disconnect       → wipes the stored token

State is signed via Flask's session cookie (Flask-Login already secures it),
preventing CSRF on the OAuth callback. The /callback route is exempted from
CSRFProtect because Jobber GETs it from outside our origin.
"""
from __future__ import annotations

import secrets

from flask import (
    Blueprint,
    abort,
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

bp = Blueprint("jobber", __name__, template_folder="../templates/jobber")


@bp.route("/")
@login_required
def index():
    has_creds = bool(current_app.config.get("JOBBER_CLIENT_ID") and
                     current_app.config.get("JOBBER_CLIENT_SECRET"))
    # Defensive: if cryptography/Jobber service can't import (e.g. Railway
    # build hasn't installed the new dep yet), don't 500 — render a helpful
    # message with the actual error so the operator knows what to do.
    connected = False
    import_error = None
    try:
        from app.services.jobber import is_connected
        if has_creds:
            connected = is_connected()
    except Exception as e:
        current_app.logger.exception("Jobber service import/check failed")
        import_error = repr(e)
    return render_template(
        "jobber/index.html",
        has_creds=has_creds,
        connected=connected,
        import_error=import_error,
    )


@bp.route("/connect", methods=["POST"])
@login_required
def connect():
    from app.services.jobber import build_authorize_url
    if not current_app.config.get("JOBBER_CLIENT_ID"):
        flash("JOBBER_CLIENT_ID env var is not set.", "error")
        return redirect(url_for("jobber.index"))
    state = secrets.token_urlsafe(24)
    session["jobber_oauth_state"] = state
    return redirect(build_authorize_url(state))


@bp.route("/callback")
@csrf.exempt
def callback():
    """Jobber redirects here after the user authorizes. NOT login_required —
    the user is in the middle of returning to our site, but we do verify
    the state token from their session matches."""
    code = request.args.get("code")
    state = request.args.get("state")
    expected = session.pop("jobber_oauth_state", None)

    if not code or not state or state != expected:
        flash("OAuth state mismatch — try connecting again.", "error")
        return redirect(url_for("jobber.index"))

    try:
        from app.services.jobber import exchange_code_for_token
        exchange_code_for_token(code)
    except Exception as e:
        current_app.logger.exception("Jobber token exchange failed")
        flash(f"Couldn't complete Jobber connection: {e}", "error")
        return redirect(url_for("jobber.index"))

    flash("Connected to Jobber. You can now sync data.", "success")
    return redirect(url_for("jobber.index"))


@bp.route("/sync/clients", methods=["POST"])
@login_required
def sync_clients():
    """Pull all Jobber clients (and their properties) via GraphQL and
    import them through the same dedup + audit pipeline as the CSV importer."""
    from dataclasses import asdict
    from app.services.jobber import fetch_all_clients
    # Reuse the CSV importer's writer, since its input shape is identical
    from scripts.import_jobber_clients import (
        ClientImport,
        PropertyImport,
        write_clients,
    )

    try:
        api_rows = fetch_all_clients(page_size=50)
    except Exception as e:
        current_app.logger.exception("Jobber sync failed")
        flash(f"Sync failed: {e}", "error")
        return redirect(url_for("jobber.index"))

    # Convert API dicts → ClientImport dataclasses (the writer's input type)
    parsed = []
    for row in api_rows:
        ci = ClientImport(
            jobber_client_id=row["jobber_client_id"],
            name=row["name"],
            phone=row["phone"],
            email=row["email"],
            is_company=row["is_company"],
            company_name=row["company_name"],
            contact_first=row["contact_first"],
            contact_last=row["contact_last"],
            lead_source=row["lead_source"],
            referred_by=row["referred_by"],
            created_at=row["created_at"],
            custom_fields=row.get("custom_fields") or {},
        )
        for p in row["properties"]:
            ci.properties.append(PropertyImport(
                label=p["label"],
                address_line1=p["address_line1"],
                address_line2=p["address_line2"],
                city=p["city"],
                state=p["state"],
                zip_code=p["zip_code"],
                county=p["county"],
                tax_rate=p["tax_rate"],
                jobber_property_id=p.get("jobber_property_id"),
                custom_fields=p.get("custom_fields") or {},
            ))
        parsed.append(ci)

    result = write_clients(parsed, commit=True)
    s = result["stats"]
    flash(
        f"Synced from Jobber: {len(parsed)} clients seen. "
        f"Created {s['clients_created']} new, "
        f"backfilled custom fields on {s.get('clients_updated', 0)} client(s) "
        f"and {s.get('properties_updated', 0)} property(ies). "
        f"Skipped {s['clients_skipped_existing']} already imported. "
        f"Created {s['properties_created']} properties.",
        "success",
    )
    return redirect(url_for("jobber.index"))


@bp.route("/sync/jobs", methods=["POST"])
@login_required
def sync_jobs_route():
    from app.services.jobber_sync import sync_jobs
    try:
        s = sync_jobs()
    except Exception as e:
        current_app.logger.exception("Job sync failed")
        flash(f"Job sync failed: {e}", "error")
        return redirect(url_for("jobber.index"))
    msg = (f"Jobs: {s['seen']} seen → {s['created']} created, "
           f"{s.get('updated', 0)} backfilled, "
           f"{s['skipped_existing']} already imported, "
           f"{s['skipped_no_client']} skipped (no matching client/property).")
    if s['errors']:
        msg += f" {len(s['errors'])} errors (check logs)."
    flash(msg, "success" if not s['errors'] else "warning")
    return redirect(url_for("jobber.index"))


@bp.route("/sync/quotes", methods=["POST"])
@login_required
def sync_quotes_route():
    from app.services.jobber_sync import sync_quotes
    try:
        s = sync_quotes()
    except Exception as e:
        current_app.logger.exception("Quote sync failed")
        flash(f"Quote sync failed: {e}", "error")
        return redirect(url_for("jobber.index"))
    msg = (f"Quotes: {s['seen']} seen → {s['created']} created, "
           f"{s.get('updated', 0)} backfilled, "
           f"{s['skipped_existing']} already imported, "
           f"{s['skipped_no_client']} skipped (no matching client/property).")
    if s['errors']:
        msg += f" {len(s['errors'])} errors."
    flash(msg, "success" if not s['errors'] else "warning")
    return redirect(url_for("jobber.index"))


@bp.route("/sync/invoices", methods=["POST"])
@login_required
def sync_invoices_route():
    from app.services.jobber_sync import sync_invoices
    try:
        s = sync_invoices()
    except Exception as e:
        current_app.logger.exception("Invoice sync failed")
        flash(f"Invoice sync failed: {e}", "error")
        return redirect(url_for("jobber.index"))
    msg = (f"Invoices: {s['seen']} seen → {s['created']} created, "
           f"{s.get('updated', 0)} backfilled, "
           f"{s['skipped_existing']} already imported, "
           f"{s['skipped_no_client']} skipped (no matching client/property). "
           f"Payments: {s['payments_created']} created.")
    if s['errors']:
        msg += f" {len(s['errors'])} errors."
    flash(msg, "success" if not s['errors'] else "warning")
    return redirect(url_for("jobber.index"))


@bp.route("/sync/all", methods=["POST"])
@login_required
def sync_all_route():
    """Kick off the full Jobber pull on a background thread (issue #5).

    The end-to-end sequence sleeps 90s between stages plus does real
    GraphQL work, which exceeded Railway/Gunicorn's 120s timeout when
    run in-request. We now start a daemon thread and let the UI poll
    `/jobber/sync/all/status` for progress.
    """
    from flask_login import current_user
    from app.services.jobber_sync_runner import start_sync_all, get_state

    started = start_sync_all(
        current_app._get_current_object(),
        started_by=getattr(current_user, "email", None),
    )
    if not started:
        state = get_state()
        stage = state.current_stage or "in progress"
        flash(f"A full Jobber sync is already running ({stage}). "
              f"Refresh in a minute to see results.", "info")
    else:
        flash("Started full Jobber sync. This runs in the background "
              "(~2–3 min) — leave this page open or refresh to see progress.",
              "info")
    return redirect(url_for("jobber.index"))


@bp.route("/sync/all/status")
@login_required
def sync_all_status():
    """Return the current background sync state as JSON for UI polling."""
    from flask import jsonify
    from app.services.jobber_sync_runner import get_state
    return jsonify(get_state().to_dict())


@bp.route("/disconnect", methods=["POST"])
@login_required
def disconnect():
    from app.services.jobber import disconnect as _disconnect
    _disconnect()
    flash("Disconnected from Jobber.", "info")
    return redirect(url_for("jobber.index"))


@bp.route("/introspect/<type_name>")
@login_required
def introspect(type_name: str):
    """Debug helper — list the fields available on a given GraphQL type.
    Usage: /jobber/introspect/PaymentRecord
    """
    from app.services.jobber import graphql
    query = """
    query Introspect($name: String!) {
      __type(name: $name) {
        name
        fields { name type { name kind ofType { name kind } } }
      }
    }
    """
    try:
        data = graphql(query, {"name": type_name})
    except Exception as e:
        return {"error": repr(e)}, 500
    t = data.get("__type")
    if not t:
        return {"error": f"No such type: {type_name}"}, 404
    fields = []
    for f in (t.get("fields") or []):
        ty = f.get("type") or {}
        of = ty.get("ofType") or {}
        type_label = ty.get("name") or of.get("name") or ty.get("kind") or "?"
        fields.append({"name": f["name"], "type": type_label})
    return {"type": t["name"], "fields": fields}
