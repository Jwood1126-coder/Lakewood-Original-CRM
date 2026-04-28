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
            ))
        parsed.append(ci)

    result = write_clients(parsed, commit=True)
    flash(
        f"Synced from Jobber: {len(parsed)} clients seen. "
        f"Created {result['stats']['clients_created']} new, "
        f"skipped {result['stats']['clients_skipped_existing']} already imported. "
        f"Created {result['stats']['properties_created']} properties.",
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
    msg = (f"Jobs: {s['created']} created, {s['skipped_existing']} already imported, "
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
    msg = (f"Quotes: {s['created']} created, {s['skipped_existing']} already imported, "
           f"{s['skipped_no_client']} skipped.")
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
    msg = (f"Invoices: {s['created']} created, {s['skipped_existing']} already imported. "
           f"Payments: {s['payments_created']} created.")
    if s['errors']:
        msg += f" {len(s['errors'])} errors."
    flash(msg, "success" if not s['errors'] else "warning")
    return redirect(url_for("jobber.index"))


@bp.route("/sync/all", methods=["POST"])
@login_required
def sync_all_route():
    """Pull everything in dependency order: clients first, then jobs/
    quotes/invoices. Each step is independent; if one fails the others
    still try."""
    results = []

    # Clients (reuses the existing endpoint's logic)
    try:
        from app.services.jobber import fetch_all_clients
        from scripts.import_jobber_clients import (
            ClientImport, PropertyImport, write_clients,
        )
        api_rows = fetch_all_clients(page_size=50)
        parsed = []
        for row in api_rows:
            ci = ClientImport(
                jobber_client_id=row["jobber_client_id"], name=row["name"],
                phone=row["phone"], email=row["email"],
                is_company=row["is_company"], company_name=row["company_name"],
                contact_first=row["contact_first"], contact_last=row["contact_last"],
                lead_source=row["lead_source"], referred_by=row["referred_by"],
                created_at=row["created_at"],
            )
            for p in row["properties"]:
                ci.properties.append(PropertyImport(
                    label=p["label"], address_line1=p["address_line1"],
                    address_line2=p["address_line2"], city=p["city"],
                    state=p["state"], zip_code=p["zip_code"],
                    county=p["county"], tax_rate=p["tax_rate"],
                    jobber_property_id=p.get("jobber_property_id"),
                ))
            parsed.append(ci)
        r = write_clients(parsed, commit=True)
        results.append(f"Clients +{r['stats']['clients_created']} "
                       f"(skipped {r['stats']['clients_skipped_existing']}); "
                       f"properties +{r['stats']['properties_created']}")
    except Exception as e:
        current_app.logger.exception("All-sync clients step failed")
        results.append(f"Clients FAILED: {e}")

    import time
    for label, fn_name in [("Jobs", "sync_jobs"),
                            ("Quotes", "sync_quotes"),
                            ("Invoices+Payments", "sync_invoices")]:
        # Cool-down between stages to let Jobber's rate limiter recover
        time.sleep(8)
        try:
            from app.services import jobber_sync as js
            s = getattr(js, fn_name)()
            extra = (f", payments +{s['payments_created']}"
                     if 'payments_created' in s else "")
            results.append(
                f"{label} +{s['created']} (skipped {s['skipped_existing']}){extra}"
            )
        except Exception as e:
            current_app.logger.exception("All-sync %s step failed", label)
            results.append(f"{label} FAILED: {e}")

    flash(" · ".join(results), "success")
    return redirect(url_for("jobber.index"))


@bp.route("/disconnect", methods=["POST"])
@login_required
def disconnect():
    from app.services.jobber import disconnect as _disconnect
    _disconnect()
    flash("Disconnected from Jobber.", "info")
    return redirect(url_for("jobber.index"))
