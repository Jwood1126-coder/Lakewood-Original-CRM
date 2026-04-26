"""Pytest fixtures."""
from __future__ import annotations

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models.user import User


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user(app):
    u = User(email="test@example.com", display_name="Test")
    u.set_password("a-very-long-test-password")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def auth_client(client, user):
    """A test client already signed in."""
    client.post(
        "/auth/login",
        data={"email": user.email, "password": "a-very-long-test-password"},
        follow_redirects=True,
    )
    return client
