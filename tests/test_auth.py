def test_login_redirect_when_anonymous(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert "/auth/login" in r.headers["Location"]


def test_login_success(client, user):
    r = client.post(
        "/auth/login",
        data={"email": user.email, "password": "a-very-long-test-password"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    # New dashboard renders today's date as the heading
    assert b"On for today" in r.data or b"Nothing scheduled yet" in r.data


def test_login_wrong_password(client, user):
    r = client.post(
        "/auth/login",
        data={"email": user.email, "password": "wrong"},
        follow_redirects=True,
    )
    assert b"Invalid" in r.data


def test_logout(auth_client):
    r = auth_client.post("/auth/logout", follow_redirects=False)
    assert r.status_code == 302
