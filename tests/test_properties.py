from decimal import Decimal


def _create_client(client):
    client.post("/clients/new",
                data={"name": "Mrs. Anderson", "phone": "5551234567"},
                follow_redirects=True)


def test_zip_autofills_county_and_tax(auth_client, app):
    from app.models.client import Client
    from app.models.property import Property
    from app.extensions import db

    _create_client(auth_client)
    c = db.session.query(Client).first()

    r = auth_client.post(
        "/properties/new",
        query_string={"client_id": c.id},
        data={
            "label": "Home",
            "address_line1": "100 Main St",
            "city": "Cleveland",
            "state": "OH",
            "zip_code": "44113",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200

    p = db.session.query(Property).first()
    assert p.county == "Cuyahoga"
    assert p.tax_rate == Decimal("0.0800")


def test_unknown_zip_falls_back_to_state_only(auth_client, app):
    from app.models.client import Client
    from app.models.property import Property
    from app.extensions import db

    _create_client(auth_client)
    c = db.session.query(Client).first()

    auth_client.post(
        "/properties/new",
        query_string={"client_id": c.id},
        data={
            "label": "Cabin",
            "address_line1": "1 Hideaway Rd",
            "city": "Nowhere",
            "state": "OH",
            "zip_code": "99999",
        },
        follow_redirects=True,
    )

    p = db.session.query(Property).first()
    assert p.county is None
    assert p.tax_rate == Decimal("0.0575")
