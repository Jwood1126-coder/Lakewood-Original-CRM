def test_create_and_view_client(auth_client):
    # Create
    r = auth_client.post(
        "/clients/new",
        data={"name": "Mrs. Anderson", "phone": "555-123-4567",
              "email": "a@example.com", "notes": "Prefers afternoons"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"Mrs. Anderson" in r.data

    # List shows the new client
    r = auth_client.get("/clients/")
    assert b"Mrs. Anderson" in r.data
    assert b"(555) 123-4567" in r.data


def test_search_clients(auth_client):
    auth_client.post("/clients/new",
                     data={"name": "Smith Rentals", "phone": "5559998877"},
                     follow_redirects=True)
    auth_client.post("/clients/new",
                     data={"name": "Mrs. Anderson", "phone": "5551234567"},
                     follow_redirects=True)

    r = auth_client.get("/clients/?q=Smith")
    assert b"Smith Rentals" in r.data
    assert b"Anderson" not in r.data

    r = auth_client.get("/clients/?q=999")  # phone-digit search
    assert b"Smith Rentals" in r.data
