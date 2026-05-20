"""Public 'request a quote' intake from the website.

Two surfaces:
  GET/POST /intake/request   → HTML form (works standalone if Jake doesn't
                                want to embed in WordPress)
  POST     /intake/api/request → JSON API (for AJAX from lakewoodoriginal.com)

Both create:
  - Client (matched by phone if existing, else new)
  - Property (under that client, address from form, OH tax-rate auto-filled)
  - Quote in 'draft' status with the customer's description as the message

Spam mitigation:
  - Per-IP rate limit (5/hr/ip)
  - Honeypot 'website' field (bots fill it; humans don't see it)
  - Required-field validation
  - No CSRF on /intake/api/request — it's a cross-origin endpoint
    (the WordPress site posts from a different domain). Not auth'd, only
    rate-limited + honeypot-protected.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import or_, select

from app.extensions import csrf, db, limiter
from app.models.client import Client
from app.models.property import Property
from app.models.quote import Quote
from app.utils.ohio_tax import lookup_county, lookup_rate
from app.utils.phone import normalize_phone
from app.utils.service_area import (
    SERVICE_AREA_CITIES,
    SERVICE_BY_KEY,
    SERVICES,
    is_in_service_area,
)

bp = Blueprint("intake", __name__, template_folder="../templates/intake")


# ---------- core: parse + persist a request ----------

def _ingest_request(form: dict, source: str) -> tuple[Client, Property, Quote] | None:
    """Validate + persist a single intake request.

    Returns (client, property, quote) on success, or None if validation
    failed / the honeypot fired.
    """
    # Honeypot — bots fill 'website'; humans never see it
    if (form.get("website") or "").strip():
        current_app.logger.warning("Intake honeypot triggered: source=%s", source)
        return None

    name = (form.get("name") or "").strip()
    phone = normalize_phone(form.get("phone"))
    email = (form.get("email") or "").strip().lower() or None
    description = (form.get("description") or "").strip()

    if not name or len(name) < 2:
        return None
    if not (phone or email):
        return None
    if not description:
        return None

    address_line1 = (form.get("address") or "").strip()
    city = (form.get("city") or "").strip()
    zip_code = (form.get("zip") or "").strip()[:10]
    service_key = (form.get("service") or "other").strip()
    service = SERVICE_BY_KEY.get(service_key, SERVICE_BY_KEY["other"])

    # Match existing client by (phone OR email) + name
    client = None
    conds = []
    if phone:
        conds.append(Client.phone == phone)
    if email:
        conds.append(Client.email == email)
    if conds:
        client = db.session.scalar(
            select(Client).where(Client.name == name, or_(*conds))
        )

    if client is None:
        client = Client(
            name=name,
            phone=phone,
            email=email,
            notes=f"[Intake from {source} on {date.today().isoformat()}]",
        )
        db.session.add(client)
        db.session.flush()
    else:
        # Don't overwrite existing contact info; just append a note
        addendum = f"\n[Returning customer; new request via {source} on {date.today().isoformat()}]"
        client.notes = (client.notes or "") + addendum

    # Property — only create if address provided
    prop = None
    if address_line1 and city:
        # Reuse property if same address already on file for this client
        existing_props = client.properties or []
        for p in existing_props:
            if (p.address_line1 or "").strip().lower() == address_line1.lower() \
                    and (p.city or "").strip().lower() == city.lower():
                prop = p
                break
        if prop is None:
            county = lookup_county(zip_code)
            prop = Property(
                client_id=client.id,
                label="Service Address",
                address_line1=address_line1,
                city=city,
                state="OH",
                zip_code=zip_code or "00000",
                county=county,
                tax_rate=Decimal(str(lookup_rate(county))),
            )
            db.session.add(prop)
            db.session.flush()
    else:
        # No address — try to use the client's first property
        prop = (client.properties or [None])[0]
        if prop is None:
            # No property at all yet; create a placeholder so the Quote FK is happy
            prop = Property(
                client_id=client.id,
                label="(address pending)",
                address_line1="(to be confirmed)",
                city=city or "Cleveland",
                state="OH",
                zip_code=zip_code or "00000",
                county=None,
                tax_rate=Decimal("0.0575"),
            )
            db.session.add(prop)
            db.session.flush()

    quote = Quote(
        client_id=client.id,
        property_id=prop.id,
        number=Quote.next_number(db.session),
        subject=f"Website request: {service['label']}",
        message_to_customer=None,
        internal_notes=(
            f"Source: {source}\n"
            f"Service category: {service['label']}\n"
            f"\nCustomer description:\n{description}"
        ),
        status="draft",
        valid_until=date.today() + timedelta(days=30),
    )
    db.session.add(quote)
    db.session.commit()

    # Fire the operator notification
    try:
        from app.services.events import notify_quote_request_received
        notify_quote_request_received(quote, source=source)
    except Exception as e:
        current_app.logger.warning("Intake notify failed: %s", e)

    return client, prop, quote


# ---------- HTML form (standalone fallback) ----------

@bp.route("/request", methods=["GET", "POST"])
@limiter.limit("8 per hour", methods=["POST"])
def request_form():
    if request.method == "POST":
        result = _ingest_request(request.form, source="self-hosted form")
        if result is None:
            return render_template(
                "intake/request.html",
                services=SERVICES, cities=SERVICE_AREA_CITIES,
                error="Please fill in your name, phone or email, and project description.",
                values=request.form,
            )
        return redirect(url_for("intake.thanks"))
    return render_template(
        "intake/request.html",
        services=SERVICES, cities=SERVICE_AREA_CITIES,
        error=None, values={},
    )


@bp.route("/thanks")
def thanks():
    return render_template("intake/thanks.html")


# ---------- JSON API for cross-origin form posts (WordPress, etc.) ----------

@bp.route("/api/request", methods=["POST", "OPTIONS"])
@csrf.exempt
@limiter.limit("8 per hour", methods=["POST"])
def api_request():
    """Accept a JSON or form-encoded POST from the WordPress contact form.

    Returns:
      200 {ok: true, quote_number: 12} on success
      400 {ok: false, error: '...'}     on validation failure / honeypot
    """
    headers = _cors_headers(request.headers.get("Origin"))

    if request.method == "OPTIONS":
        # CORS preflight. If the Origin isn't on our allow-list, return 403
        # with no CORS headers so the browser refuses to make the real call.
        if "Access-Control-Allow-Origin" not in headers:
            return ("", 403, {})
        return ("", 204, headers)

    payload = request.get_json(silent=True) or request.form
    result = _ingest_request(payload or {}, source="website")
    if result is None:
        return (jsonify(ok=False,
                         error="Missing required fields or spam check failed"),
                400, headers)
    _, _, quote = result
    return (jsonify(ok=True, quote_number=quote.number,
                     message="Thanks — we'll be in touch shortly."),
            200, headers)


def _cors_headers(origin: str | None) -> dict:
    """Build CORS headers for the given request Origin (issue #4).

    Echoes the Origin back only when it appears in the configured allow-list
    (`INTAKE_CORS_ORIGINS`). For non-allowed or missing origins we omit the
    `Access-Control-Allow-Origin` header entirely; browsers then refuse the
    response. `Vary: Origin` is always set so caches can't pollute responses
    between callers.
    """
    base = {
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Vary": "Origin",
    }
    allowed = current_app.config.get("INTAKE_CORS_ORIGINS") or []
    if origin and origin in allowed:
        base["Access-Control-Allow-Origin"] = origin
    return base
