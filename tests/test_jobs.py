from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.models.client import Client
from app.models.job import Job
from app.models.property import Property
from app.models.visit import Visit


def _make_client_property(app):
    c = Client(name="Mrs. Anderson", phone="5551234567")
    p = Property(client=c, label="Home", address_line1="100 Main",
                 city="Cleveland", state="OH", zip_code="44113")
    db.session.add_all([c, p])
    db.session.commit()
    return c, p


def test_create_job_via_form(auth_client, app):
    c, p = _make_client_property(app)
    r = auth_client.post(
        "/jobs/new",
        data={
            "title": "Replace kitchen faucet",
            "client_id": c.id,
            "property_id": p.id,
            "scope": "Pull old, install new",
            "scheduled_date": "2026-05-05",
            "scheduled_time": "09:00",
            "est_hours": "2",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"Replace kitchen faucet" in r.data
    j = db.session.query(Job).first()
    assert j.status == "scheduled"
    assert j.scheduled_date == date(2026, 5, 5)


def test_status_transition_blocks_invalid(app):
    c, p = _make_client_property(app)
    j = Job(client=c, prop=p, title="x", status="scheduled")
    db.session.add(j); db.session.commit()
    assert j.can_transition_to("in_progress")
    assert not j.can_transition_to("scheduled")  # already scheduled
    j.transition_to("complete")
    assert j.status == "complete"


def test_start_visit_creates_active_visit(auth_client, app):
    c, p = _make_client_property(app)
    j = Job(client=c, prop=p, title="x", status="scheduled")
    db.session.add(j); db.session.commit()

    auth_client.post(f"/jobs/{j.id}/visits/start")
    db.session.refresh(j)
    assert j.status == "in_progress"
    assert len(j.visits) == 1
    v = j.visits[0]
    assert v.is_active
    assert v.arrived_at is not None
    assert v.departed_at is None


def test_end_visit_records_departure(auth_client, app):
    c, p = _make_client_property(app)
    j = Job(client=c, prop=p, title="x", status="scheduled")
    db.session.add(j); db.session.commit()

    auth_client.post(f"/jobs/{j.id}/visits/start")
    auth_client.post(f"/jobs/{j.id}/visits/end")
    db.session.refresh(j)
    v = j.visits[0]
    assert not v.is_active
    assert v.duration is not None


def test_today_dashboard_shows_today_jobs(auth_client, app):
    c, p = _make_client_property(app)
    today_job = Job(client=c, prop=p, title="Roof repair today",
                    status="scheduled", scheduled_date=date.today())
    db.session.add(today_job); db.session.commit()

    r = auth_client.get("/")
    assert r.status_code == 200
    assert b"Roof repair today" in r.data


def test_calendar_renders(auth_client, app):
    _make_client_property(app)
    r = auth_client.get("/jobs/calendar")
    assert r.status_code == 200
    assert b"Calendar" in r.data


def test_repeat_job_prefills(auth_client, app):
    c, p = _make_client_property(app)
    src = Job(client=c, prop=p, title="Mow lawn",
              scope="Front+back", est_hours=1.5, status="complete")
    db.session.add(src); db.session.commit()

    r = auth_client.get(f"/jobs/new?repeat_from={src.id}")
    assert r.status_code == 200
    assert b"Mow lawn" in r.data
    assert b"Front+back" in r.data
