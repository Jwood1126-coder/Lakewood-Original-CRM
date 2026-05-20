"""Regression tests for M0 Stabilize: issues #2, #3, #4, #5.

These tests are intentionally narrow — they pin the specific bugs/
behaviors called out in each GitHub issue so future refactors can't
silently regress them.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.client import Client
from app.models.property import Property
from app.models.quote import Quote


# ----- shared fixtures -----

def _make_client_and_property() -> tuple[Client, Property]:
    c = Client(name="State Machine Customer", phone="2165550199")
    p = Property(client=c, label="Home",
                 address_line1="200 Main St", city="Cleveland", state="OH",
                 zip_code="44113", county="Cuyahoga", tax_rate=Decimal("0.08"))
    db.session.add_all([c, p])
    db.session.commit()
    return c, p


# =============================================================
# Issue #2 — Settings > Notifications form should not crash.
# Regression: NotificationForm.notify_email_to was misplaced on
# JobberClientsImportForm, so /settings/notifications crashed on save.
# =============================================================

class TestIssue2NotificationForm:
    def test_notification_form_has_notify_email_to_field(self):
        from app.settings.forms import NotificationForm
        # WTForms exposes fields as class attributes via UnboundField.
        assert hasattr(NotificationForm, "notify_email_to")

    def test_jobber_import_form_does_not_have_notify_email_to(self):
        from app.settings.forms import JobberClientsImportForm
        assert not hasattr(JobberClientsImportForm, "notify_email_to")

    def test_jobber_import_form_submit_label_is_import(self, app):
        """Double-submit declaration previously overrode the import button."""
        from app.settings.forms import JobberClientsImportForm
        with app.test_request_context():
            form = JobberClientsImportForm(meta={"csrf": False})
            assert form.submit.label.text == "Import"

    def test_notifications_get_renders(self, auth_client):
        r = auth_client.get("/settings/notifications")
        assert r.status_code == 200
        assert b"notify_email_to" in r.data or b"name=\"notify_email_to\"" in r.data

    def test_notifications_post_saves_without_crashing(self, auth_client):
        """The original bug: POST to /settings/notifications crashed because
        notify_email_to lived on the wrong form. This is the smoke test."""
        r = auth_client.post(
            "/settings/notifications",
            data={
                "daily_briefing": "y",
                "daily_time": "06:30",
                "weekly_briefing": "y",
                "monthly_report": "y",
                "job_day_reminder": "y",
                "event_quote_request_received": "y",
                "event_quote_sent": "y",
                "event_quote_accepted": "y",
                "event_quote_converted": "y",
                "event_job_complete": "y",
                "event_invoice_sent": "y",
                "event_invoice_paid": "y",
                "event_payment_received": "y",
                "email_channel": "y",
                "notify_email_to": "jake@example.com",
                "submit": "Save notification preferences",
            },
            follow_redirects=False,
        )
        # Successful save redirects back to /settings/notifications
        assert r.status_code in (302, 303)
        # And the value got persisted via the settings table
        from app.models.setting import get_setting
        assert get_setting("notify_email_to") == "jake@example.com"


# =============================================================
# Issue #3 — Quote state-machine guards on change_status.
# Mirrors Job/Invoice protections. Disallow draft → accepted (skipping
# 'sent'), and disallow leaving the terminal 'converted' state.
# =============================================================

class TestIssue3QuoteStateMachine:

    def test_allowed_transitions_table_is_complete(self):
        """Every known status must have an entry in the transition table —
        otherwise calling can_transition_to from that status silently
        returns False for everything (which is also fine, but should be
        intentional)."""
        from app.models.quote import QUOTE_STATUSES, _QUOTE_ALLOWED_TRANSITIONS
        for s in QUOTE_STATUSES:
            assert s in _QUOTE_ALLOWED_TRANSITIONS, f"missing transitions for {s!r}"

    def test_draft_to_sent_allowed(self, app):
        c, p = _make_client_and_property()
        q = Quote(client=c, prop=p, number=1, subject="x", status="draft")
        db.session.add(q); db.session.commit()
        assert q.can_transition_to("sent") is True

    def test_draft_to_accepted_disallowed(self, app):
        c, p = _make_client_and_property()
        q = Quote(client=c, prop=p, number=1, subject="x", status="draft")
        db.session.add(q); db.session.commit()
        assert q.can_transition_to("accepted") is False

    def test_converted_is_terminal(self, app):
        c, p = _make_client_and_property()
        q = Quote(client=c, prop=p, number=1, subject="x", status="converted")
        db.session.add(q); db.session.commit()
        # Can't move off converted to anything
        for s in ("draft", "sent", "accepted", "declined", "expired"):
            assert q.can_transition_to(s) is False, f"converted→{s} should be blocked"

    def test_unknown_status_disallowed(self, app):
        c, p = _make_client_and_property()
        q = Quote(client=c, prop=p, number=1, subject="x", status="draft")
        db.session.add(q); db.session.commit()
        assert q.can_transition_to("magicked") is False

    def test_transition_to_raises_on_bad_transition(self, app):
        c, p = _make_client_and_property()
        q = Quote(client=c, prop=p, number=1, subject="x", status="draft")
        db.session.add(q); db.session.commit()
        with pytest.raises(ValueError):
            q.transition_to("accepted")

    def test_change_status_route_blocks_illegal_jump(self, auth_client, app):
        c, p = _make_client_and_property()
        q = Quote(client=c, prop=p, number=1, subject="x", status="draft")
        db.session.add(q); db.session.commit()
        r = auth_client.post(f"/quotes/{q.id}/status/accepted",
                             follow_redirects=False)
        assert r.status_code in (302, 303)
        db.session.refresh(q)
        assert q.status == "draft", "illegal draft→accepted must not mutate status"

    def test_change_status_route_walks_draft_sent_accepted(self, auth_client, app):
        c, p = _make_client_and_property()
        q = Quote(client=c, prop=p, number=1, subject="x", status="draft")
        db.session.add(q); db.session.commit()
        auth_client.post(f"/quotes/{q.id}/status/sent")
        db.session.refresh(q)
        assert q.status == "sent"
        assert q.sent_at is not None
        auth_client.post(f"/quotes/{q.id}/status/accepted")
        db.session.refresh(q)
        assert q.status == "accepted"
        assert q.accepted_at is not None

    def test_change_status_route_blocks_explicit_converted(self, auth_client, app):
        """Even though the state machine allows sent→converted, the route
        forces operators to use /convert-to-job so the linked Job actually
        gets created."""
        c, p = _make_client_and_property()
        q = Quote(client=c, prop=p, number=1, subject="x", status="sent")
        db.session.add(q); db.session.commit()
        auth_client.post(f"/quotes/{q.id}/status/converted")
        db.session.refresh(q)
        assert q.status == "sent"
        assert q.converted_to_job_id is None


# =============================================================
# Issue #4 — Intake CORS allow-list driven by env, not a hardcoded
# single origin. Allowed origins get echoed back; everything else
# gets no ACAO header.
# =============================================================

class TestIssue4IntakeCORS:

    def _set_allowlist(self, app, origins: list[str]):
        app.config["INTAKE_CORS_ORIGINS"] = origins

    def test_default_allowlist_includes_prod_and_www(self, app):
        origins = app.config.get("INTAKE_CORS_ORIGINS") or []
        assert "https://lakewoodoriginal.com" in origins
        assert "https://www.lakewoodoriginal.com" in origins

    def test_preflight_from_allowed_origin_echoes_origin(self, client, app):
        self._set_allowlist(app, ["https://lakewoodoriginal.com"])
        r = client.options(
            "/intake/api/request",
            headers={"Origin": "https://lakewoodoriginal.com"},
        )
        assert r.status_code == 204
        assert r.headers.get("Access-Control-Allow-Origin") == "https://lakewoodoriginal.com"
        assert "Origin" in (r.headers.get("Vary") or "")

    def test_preflight_from_www_origin_when_in_allowlist(self, client, app):
        self._set_allowlist(app, [
            "https://lakewoodoriginal.com",
            "https://www.lakewoodoriginal.com",
        ])
        r = client.options(
            "/intake/api/request",
            headers={"Origin": "https://www.lakewoodoriginal.com"},
        )
        assert r.status_code == 204
        assert r.headers.get("Access-Control-Allow-Origin") == "https://www.lakewoodoriginal.com"

    def test_preflight_from_denied_origin_is_403(self, client, app):
        self._set_allowlist(app, ["https://lakewoodoriginal.com"])
        r = client.options(
            "/intake/api/request",
            headers={"Origin": "https://evil.example.com"},
        )
        # No ACAO header → browser refuses the response anyway. We make
        # that more explicit on preflight by returning 403.
        assert r.status_code == 403
        assert "Access-Control-Allow-Origin" not in r.headers

    def test_post_from_denied_origin_omits_acao(self, client, app):
        """Non-allowed POSTs still execute (the API stays public for
        the HTML form), but the browser gets no ACAO header so a cross-
        origin caller can't read the response."""
        self._set_allowlist(app, ["https://lakewoodoriginal.com"])
        r = client.post(
            "/intake/api/request",
            json={
                "name": "Test Person",
                "phone": "2165550100",
                "description": "hello world",
            },
            headers={"Origin": "https://evil.example.com"},
        )
        assert r.status_code in (200, 400)
        assert "Access-Control-Allow-Origin" not in r.headers

    def test_post_from_allowed_origin_includes_acao(self, client, app):
        self._set_allowlist(app, ["https://lakewoodoriginal.com"])
        r = client.post(
            "/intake/api/request",
            json={
                "name": "Test Person",
                "phone": "2165550100",
                "description": "hello world",
            },
            headers={"Origin": "https://lakewoodoriginal.com"},
        )
        assert r.status_code in (200, 400)
        assert r.headers.get("Access-Control-Allow-Origin") == "https://lakewoodoriginal.com"


# =============================================================
# Issue #5 — /jobber/sync/all must not hold a worker for ~90s.
# We don't actually call Jobber's API in tests; we monkeypatch the
# sync functions and the cool-down sleep to 0, then assert the
# runner state advances and the route returns immediately.
# =============================================================

class TestIssue5SyncAllBackgrounded:

    @pytest.fixture(autouse=True)
    def _reset(self):
        from app.services.jobber_sync_runner import reset_state_for_tests
        reset_state_for_tests()
        yield
        reset_state_for_tests()

    def _patch_stages(self, monkeypatch):
        """Replace the four real sync functions with cheap stand-ins."""
        from app.services import jobber_sync_runner as runner

        def fake_clients_stage():
            return "Clients +1 (skipped 0); properties +1"

        monkeypatch.setattr(runner, "_run_clients_stage", fake_clients_stage)

        # Replace jobber_sync's sync_jobs/quotes/invoices via the module
        # the runner imports lazily.
        from app.services import jobber_sync
        monkeypatch.setattr(jobber_sync, "sync_jobs",
                             lambda: {"created": 1, "skipped_existing": 0,
                                      "seen": 1, "errors": []}, raising=False)
        monkeypatch.setattr(jobber_sync, "sync_quotes",
                             lambda: {"created": 1, "skipped_existing": 0,
                                      "seen": 1, "errors": []}, raising=False)
        monkeypatch.setattr(jobber_sync, "sync_invoices",
                             lambda: {"created": 1, "skipped_existing": 0,
                                      "seen": 1, "payments_created": 0,
                                      "errors": []}, raising=False)

    def test_run_sync_all_inline_walks_all_stages(self, app, monkeypatch):
        self._patch_stages(monkeypatch)
        from app.services.jobber_sync_runner import run_sync_all_inline
        # Skip the 30s cool-downs
        final = run_sync_all_inline(app, sleep_fn=lambda _s: None)
        assert final.running is False
        assert final.finished_at is not None
        assert len(final.results) == 4
        joined = " | ".join(final.results)
        assert "Clients" in joined
        assert "Jobs" in joined
        assert "Quotes" in joined
        assert "Invoices+Payments" in joined

    def test_route_returns_immediately_and_starts_background(self, auth_client, app, monkeypatch):
        """The POST to /jobber/sync/all must redirect immediately even
        though the underlying sync would normally sleep 90s+."""
        import time
        self._patch_stages(monkeypatch)
        t0 = time.monotonic()
        r = auth_client.post("/jobber/sync/all", follow_redirects=False)
        elapsed = time.monotonic() - t0
        assert r.status_code in (302, 303)
        assert elapsed < 2.0, f"sync_all_route took {elapsed}s — must not block"

    def test_status_endpoint_returns_json(self, auth_client, app, monkeypatch):
        self._patch_stages(monkeypatch)
        # Drive a synchronous run so state is populated deterministically.
        from app.services.jobber_sync_runner import run_sync_all_inline
        run_sync_all_inline(app, sleep_fn=lambda _s: None)

        r = auth_client.get("/jobber/sync/all/status")
        assert r.status_code == 200
        payload = r.get_json()
        assert payload is not None
        assert payload["running"] is False
        assert payload["finished_at"] is not None
        assert len(payload["results"]) == 4

    def test_second_start_while_running_is_noop(self, app, monkeypatch):
        """Two operators clicking the button shouldn't kick off two
        concurrent syncs."""
        from app.services import jobber_sync_runner as runner
        # Force the runner to look "running" without actually launching a thread
        with runner._state_lock:
            runner._state.running = True
            runner._state.started_at = None
        started = runner.start_sync_all(app)
        assert started is False
