"""Phone number normalization (US-only for v1)."""
from __future__ import annotations


def normalize_phone(raw: str | None) -> str | None:
    """Strip non-digits, drop a leading '1', return digits or None.

    Matches what we want to *store* (digits-only). Display formatting
    happens in the model's `display_phone` property.
    """
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if not digits:
        return None
    return digits
