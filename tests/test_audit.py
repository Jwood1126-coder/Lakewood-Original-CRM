from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.audit_log import AuditLog
from app.models.client import Client
from app.models.job import Job
from app.models.property import Property


def test_insert_creates_audit_row(app):
    c = Client(name="Test Co")
    db.session.add(c)
    db.session.commit()

    rows = db.session.query(AuditLog).order_by(AuditLog.id).all()
    assert len(rows) == 1
    r = rows[0]
    assert r.operation == "insert"
    assert r.entity_type == "Client"
    assert r.entity_id == c.id
    assert r.before_json is None
    assert "Test Co" in (r.after_json or "")


def test_update_captures_before_after(app):
    """Realistic flow: load via session.get() (mirrors how Flask routes
    fetch then mutate). PASSIVE_OFF in audit.py loads expired attrs so
    history.deleted has the real previous value."""
    c = Client(name="Original")
    db.session.add(c); db.session.commit()
    cid = c.id
    db.session.query(AuditLog).delete(); db.session.commit()
    db.session.expire_all()

    c2 = db.session.get(Client, cid)
    _ = c2.name  # ensure attribute is loaded
    c2.name = "Renamed"
    db.session.commit()

    rows = (db.session.query(AuditLog)
            .filter_by(operation="update", entity_type="Client", entity_id=cid)
            .all())
    assert len(rows) == 1
    r = rows[0]
    assert "Original" in (r.before_json or "")
    assert "Renamed" in (r.after_json or "")


def test_delete_captures_full_snapshot(app):
    c = Client(name="To Delete")
    db.session.add(c); db.session.commit()
    cid = c.id
    db.session.query(AuditLog).delete(); db.session.commit()

    db.session.delete(c)
    db.session.commit()

    rows = (db.session.query(AuditLog)
            .filter_by(operation="delete", entity_type="Client", entity_id=cid).all())
    assert len(rows) >= 1
    assert "To Delete" in (rows[0].before_json or "")


def test_settings_changes_are_not_audited(app):
    """Setting/Conversation/Notification etc. are intentionally skipped."""
    from app.models.setting import set_setting
    db.session.query(AuditLog).delete(); db.session.commit()
    set_setting("business_name", "Test Biz")
    rows = db.session.query(AuditLog).all()
    assert len(rows) == 0
