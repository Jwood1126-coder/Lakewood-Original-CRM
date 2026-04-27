"""Regression tests for the issues found in the agent code review.

References to the H#/M#/L# numbers from the review report.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from app.extensions import db
from app.models.client import Client
from app.models.invoice import Invoice
from app.models.line_item import LineItem
from app.models.payment import Payment
from app.models.property import Property
from app.models.quote import Quote


def _setup_cp(app):
    c = Client(name="Test Co", phone="2165550100")
    p = Property(client=c, label="HQ", address_line1="1 Main St",
                 city="Cleveland", state="OH", zip_code="44113",
                 county="Cuyahoga", tax_rate=Decimal("0.0800"))
    db.session.add_all([c, p]); db.session.commit()
    return c, p


# H2 — quote convert validation -----------------------------------------

def test_h2_cannot_convert_draft_quote(auth_client, app):
    c, p = _setup_cp(app)
    q = Quote(client=c, prop=p, number=1, subject="x", status="draft")
    db.session.add(q); db.session.commit()
    r = auth_client.post(f"/quotes/{q.id}/convert-to-job", follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(q)
    assert q.converted_to_job_id is None
    assert q.status == "draft"


def test_h2_can_convert_sent_quote(auth_client, app):
    c, p = _setup_cp(app)
    q = Quote(client=c, prop=p, number=1, subject="x", status="sent")
    db.session.add(q); db.session.commit()
    r = auth_client.post(f"/quotes/{q.id}/convert-to-job", follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(q)
    assert q.converted_to_job_id is not None
    assert q.status == "converted"
    assert q.accepted_at is not None  # auto-set on convert


# H7 — N+1 fix via paid_cents_bulk --------------------------------------

def test_h7_paid_cents_bulk_returns_correct_totals(app):
    c, p = _setup_cp(app)
    inv1 = Invoice(client=c, prop=p, number=1001, subject="a", status="sent")
    inv2 = Invoice(client=c, prop=p, number=1002, subject="b", status="sent")
    inv3 = Invoice(client=c, prop=p, number=1003, subject="c", status="sent")
    db.session.add_all([inv1, inv2, inv3]); db.session.flush()
    db.session.add_all([
        Payment(invoice_id=inv1.id, amount_cents=5000, method="check"),
        Payment(invoice_id=inv1.id, amount_cents=2500, method="check"),
        Payment(invoice_id=inv2.id, amount_cents=10000, method="zelle"),
        # inv3 has no payments
    ])
    db.session.commit()

    result = Invoice.paid_cents_bulk([inv1.id, inv2.id, inv3.id])
    assert result[inv1.id] == 7500
    assert result[inv2.id] == 10000
    assert result[inv3.id] == 0


def test_h7_cache_used_when_set(app):
    c, p = _setup_cp(app)
    inv = Invoice(client=c, prop=p, number=1001, subject="x", status="sent")
    db.session.add(inv); db.session.flush()
    db.session.add(LineItem(invoice_id=inv.id, description="x",
                             quantity=Decimal("1"), unit_price_cents=10000,
                             taxable=False))
    db.session.add(Payment(invoice_id=inv.id, amount_cents=3000, method="check"))
    db.session.commit()

    # Without cache: real value
    assert inv.paid_cents == 3000
    # Set cache; property should return cached value
    inv._paid_cents_cache = 9999
    assert inv.paid_cents == 9999


# M11 — invoice state machine -------------------------------------------

def test_m11_paid_to_sent_blocked(auth_client, app):
    c, p = _setup_cp(app)
    inv = Invoice(client=c, prop=p, number=1001, subject="x", status="paid")
    db.session.add(inv); db.session.commit()
    assert not inv.can_transition_to("sent")
    r = auth_client.post(f"/invoices/{inv.id}/status/sent", follow_redirects=True)
    assert r.status_code == 200
    db.session.refresh(inv)
    assert inv.status == "paid"  # unchanged


def test_m11_paid_to_void_allowed(app):
    c, p = _setup_cp(app)
    inv = Invoice(client=c, prop=p, number=1001, subject="x", status="paid")
    db.session.add(inv); db.session.commit()
    assert inv.can_transition_to("void")


def test_m11_draft_cannot_be_marked_paid(app):
    c, p = _setup_cp(app)
    inv = Invoice(client=c, prop=p, number=1001, subject="x", status="draft")
    db.session.add(inv); db.session.commit()
    assert not inv.can_transition_to("paid")
    assert not inv.can_transition_to("partial")


# L6 — invoice with payments cannot be deleted --------------------------

def test_l6_invoice_with_payments_cannot_be_deleted(auth_client, app):
    c, p = _setup_cp(app)
    inv = Invoice(client=c, prop=p, number=1001, subject="x", status="sent")
    db.session.add(inv); db.session.flush()
    db.session.add(Payment(invoice_id=inv.id, amount_cents=1000, method="check"))
    db.session.commit()
    inv_id = inv.id

    r = auth_client.post(f"/invoices/{inv_id}/delete", follow_redirects=True)
    assert r.status_code == 200
    # Invoice still exists
    assert db.session.get(Invoice, inv_id) is not None
    assert b"cannot be deleted" in r.data


def test_l6_invoice_without_payments_can_be_deleted(auth_client, app):
    c, p = _setup_cp(app)
    inv = Invoice(client=c, prop=p, number=1001, subject="x", status="sent")
    db.session.add(inv); db.session.commit()
    inv_id = inv.id

    auth_client.post(f"/invoices/{inv_id}/delete", follow_redirects=True)
    assert db.session.get(Invoice, inv_id) is None


# M1/M5 — TZ helper consistency -----------------------------------------

def test_m1_today_local_returns_a_date(app):
    from app.utils.timezone import today_local
    t = today_local()
    assert isinstance(t, date)
    # And it's within 1 day of UTC today (TZ offset can shift it)
    assert abs((t - date.today()).days) <= 1
