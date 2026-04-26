from decimal import Decimal

from app.utils.ohio_tax import lookup_county, lookup_rate, rate_for_zip


def test_known_zip_resolves_to_county():
    assert lookup_county("44113") == "Cuyahoga"
    assert lookup_county("44060") == "Lake"


def test_unknown_zip_returns_none():
    assert lookup_county("99999") is None
    assert lookup_county(None) is None
    assert lookup_county("") is None


def test_known_county_resolves_to_rate():
    assert lookup_rate("Cuyahoga") == Decimal("0.0800")


def test_unknown_county_falls_back_to_state_only():
    assert lookup_rate("Atlantis") == Decimal("0.0575")
    assert lookup_rate(None) == Decimal("0.0575")


def test_rate_for_zip_combined():
    county, rate = rate_for_zip("44113")
    assert county == "Cuyahoga"
    assert rate == Decimal("0.0800")

    county, rate = rate_for_zip("99999")
    assert county is None
    assert rate == Decimal("0.0575")
