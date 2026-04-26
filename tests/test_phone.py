from app.utils.phone import normalize_phone


def test_strips_formatting():
    assert normalize_phone("(555) 123-4567") == "5551234567"


def test_drops_us_country_code():
    assert normalize_phone("1-555-123-4567") == "5551234567"


def test_returns_none_for_blank():
    assert normalize_phone(None) is None
    assert normalize_phone("") is None
    assert normalize_phone("   ") is None


def test_keeps_short_numbers():
    # Short numbers (extensions etc.) returned as-is digits
    assert normalize_phone("555") == "555"
