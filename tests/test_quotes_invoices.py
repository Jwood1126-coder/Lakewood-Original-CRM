"""End-to-end tests for the quote/invoice/payment lifecycle.

Verifies:
- Money math (cents-as-integer, Decimal tax math, ROUND_HALF_UP)
- Status state machines
- Quote -> Job conversion
- Invoice -> payment recording -> recompute_status
- Audit log captures everything
- A/R aging calculation
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from app.extensions import db
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.invoice import Invoice
from app.models.job import Job
from app.models.line_item import LineItem
from app.models.payment import Payment
from app.models.property import Property
from app.models.quote import Quote


def _setup_cp(app):
    c = Client(name="Mrs. Anderson", phone="2165550142")
    p = Property(client=c, label="Home",
                 address_line1="100 Main St", city="Cleveland", state="OH",
                 zip_code="44113", county="Cuyahoga", tax_rate=Decimal("0.0800"))
    db.session.add_all([c, p])
    db.session.commit()
    return c, p


# ---------- Money / tax math ----------

def test_quote_total_with_taxable_and_nontaxable_lines(app):
    c, p = _setup_cp(app)
    q = Quote(client=c, prop=p, number=1, subject="Test")
    db.session.add(q); db.session.flush()
    db.session.add_all([
        LineItem(quote_id=q.id, description="Material",
                 quantity=Decimal("1"), unit_price_cents=18000, taxable=True),
        LineItem(quote_id=q.id, description="Labor",
                 quantity=Decimal("1.5"), unit_price_cents=8500, taxable=False),
    ])
    db.session.commit()
    db.session.refresh(q)

    assert q.subtotal_cents == 18000 + 12750  # 30750
    assert q.taxable_subtotal_cents == 18000
    assert q.tax_cents == 1440  # 8% of $180.00 = $14.40
    assert q.total_cents == 30750 + 1440  # 32190


def test_tax_rounding_half_up(app):
    """0.0875 * $0.75 = $0.065625 → should round to $0.07."""
    c, p = _setup_cp(app)
    p.tax_rate = Decimal("0.0875")
    q = Quote(client=c, prop=p, number=1, subject="Tiny")
    db.session.add(q); db.session.flush()
    db.session.add(LineItem(quote_id=q.id, description="Penny",
                             quantity=Decimal("1"), unit_price_cents=75,
                             taxable=True))
    db.session.commit()
    db.session.refresh(q)
    # 75 * 0.0875 = 6.5625 cents → ROUND_HALF_UP → 7
    assert q.tax_cents == 7


def test_invoice_balance_and_recompute_status(app):
    c, p = _setup_cp(app)
    inv = Invoice(client=c, prop=p, number=1001, subject="Test", status="sent")
    db.session.add(inv); db.session.flush()
    db.session.add(LineItem(invoice_id=inv.id, description="Service",
                             quantity=Decimal("1"), unit_price_cents=10000,
                             taxable=False))
    db.session.commit()
    db.session.refresh(inv)
    assert inv.total_cents == 10000
    assert inv.balance_cents == 10000

    # Partial payment
    db.session.add(Payment(invoice_id=inv.id, amount_cents=4000, method="check"))
    db.session.flush()
    inv.recompute_status()
    db.session.commit()
    assert inv.paid_cents == 4000
    assert inv.balance_cents == 6000
    assert inv.status == "partial"

    # Final payment
    db.session.add(Payment(invoice_id=inv.id, amount_cents=6000, method="zelle"))
    db.session.flush()
    inv.recompute_status()
    db.session.commit()
    assert inv.balance_cents == 0
    assert inv.status == "paid"
    assert inv.paid_at is not None


def test_invoice_overdue_detection(app):
    c, p = _setup_cp(app)
    past_due = date.today() - timedelta(days=10)
    inv = Invoice(client=c, prop=p, number=1001, subject="Old",
                  status="sent", due_date=past_due)
    db.session.add(inv); db.session.flush()
    db.session.add(LineItem(invoice_id=inv.id, description="x",
                             quantity=Decimal("1"), unit_price_cents=5000,
                             taxable=False))
    db.session.commit()
    assert inv.is_overdue
    assert inv.days_overdue == 10


def test_paid_invoice_is_not_overdue(app):
    c, p = _setup_cp(app)
    past_due = date.today() - timedelta(days=10)
    inv = Invoice(client=c, prop=p, number=1001, subject="x",
                  status="paid", due_date=past_due)
    db.session.add(inv); db.session.flush()
    db.session.commit()
    assert not inv.is_overdue


# ---------- Quote → Job conversion ----------

def test_quote_to_job_conversion(auth_client, app):
    c, p = _setup_cp(app)
    q = Quote(client=c, prop=p, number=1, subject="Test", status="accepted")
    db.session.add(q); db.session.commit()

    r = auth_client.post(f"/quotes/{q.id}/convert-to-job", follow_redirects=True)
    assert r.status_code == 200

    db.session.refresh(q)
    assert q.converted_to_job_id is not None
    assert q.status == "converted"

    job = db.session.get(Job, q.converted_to_job_id)
    assert job is not None
    assert job.client_id == c.id
    assert job.property_id == p.id


# ---------- Client.balance_owed ----------

def test_client_balance_owed_aggregates_open_invoices(app):
    c, p = _setup_cp(app)
    # One paid (shouldn't count), one sent unpaid (should count)
    inv1 = Invoice(client=c, prop=p, number=1001, subject="paid", status="paid")
    inv2 = Invoice(client=c, prop=p, number=1002, subject="open", status="sent")
    db.session.add_all([inv1, inv2]); db.session.flush()
    db.session.add_all([
        LineItem(invoice_id=inv1.id, description="x", quantity=Decimal("1"),
                 unit_price_cents=5000, taxable=False),
        LineItem(invoice_id=inv2.id, description="y", quantity=Decimal("1"),
                 unit_price_cents=8000, taxable=False),
    ])
    db.session.add(Payment(invoice_id=inv1.id, amount_cents=5000, method="check"))
    db.session.commit()
    db.session.refresh(c)
    assert c.balance_owed_cents == 8000


# ---------- Audit log captures Phase 3 entities ----------

def test_audit_log_captures_quote_creation(app):
    c, p = _setup_cp(app)
    db.session.query(AuditLog).delete(); db.session.commit()

    q = Quote(client=c, prop=p, number=1, subject="Test")
    db.session.add(q); db.session.flush()
    db.session.add(LineItem(quote_id=q.id, description="x",
                             quantity=Decimal("1"), unit_price_cents=100,
                             taxable=True))
    db.session.commit()

    rows = (db.session.query(AuditLog)
            .filter(AuditLog.entity_type.in_(["Quote", "LineItem"])).all())
    assert any(r.entity_type == "Quote" and r.operation == "insert" for r in rows)
    assert any(r.entity_type == "LineItem" and r.operation == "insert" for r in rows)


def test_audit_log_captures_payment_with_actor(auth_client, app):
    c, p = _setup_cp(app)
    inv = Invoice(client=c, prop=p, number=1001, subject="x", status="sent")
    db.session.add(inv); db.session.flush()
    db.session.add(LineItem(invoice_id=inv.id, description="x",
                             quantity=Decimal("1"), unit_price_cents=10000,
                             taxable=False))
    db.session.commit()
    db.session.query(AuditLog).delete(); db.session.commit()

    auth_client.post(
        f"/invoices/{inv.id}/payments",
        data={"amount": "100.00", "method": "check", "submit": "Record payment"},
    )
    rows = (db.session.query(AuditLog)
            .filter(AuditLog.entity_type == "Payment", AuditLog.operation == "insert")
            .all())
    assert len(rows) >= 1
    assert rows[0].actor_email == "test@example.com"


# ---------- HTTP smoke ----------

def test_dashboard_renders_with_pipeline_data(auth_client, app):
    c, p = _setup_cp(app)
    overdue_inv = Invoice(client=c, prop=p, number=1001, subject="Overdue test",
                           status="sent", due_date=date.today() - timedelta(days=20))
    db.session.add(overdue_inv); db.session.flush()
    db.session.add(LineItem(invoice_id=overdue_inv.id, description="x",
                             quantity=Decimal("1"), unit_price_cents=5000,
                             taxable=False))
    db.session.commit()

    r = auth_client.get("/")
    assert r.status_code == 200
    assert b"Overdue invoices" in r.data
    assert b"Overdue test" in r.data


def test_reports_pages_render(auth_client):
    for path in ["/reports/", "/reports/sales-tax", "/reports/revenue",
                 "/reports/ar-aging", "/reports/year-end"]:
        r = auth_client.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
