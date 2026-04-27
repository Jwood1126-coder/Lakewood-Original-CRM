"""Money helpers — keep all $ math here, not scattered across views."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def dollars_to_cents(s: str | float | Decimal | None) -> int:
    """Parse a user-entered dollar string ('45.50', '$1,200', '0') to integer cents.

    Tolerant of $, commas, whitespace. Returns 0 for empty/falsy input.
    Negative numbers and bad input raise ValueError.
    """
    if s is None or s == "":
        return 0
    if isinstance(s, (int, float)):
        d = Decimal(str(s))
    else:
        cleaned = (str(s).strip()
                          .replace("$", "")
                          .replace(",", ""))
        if not cleaned:
            return 0
        d = Decimal(cleaned)
    if d < 0:
        raise ValueError("Amount must be non-negative")
    cents = (d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def cents_to_str(cents: int) -> str:
    """Format integer cents as '$1,234.50'."""
    if cents is None:
        return "$0.00"
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    dollars, c = divmod(cents, 100)
    # Add comma thousands separator
    return f"{sign}${dollars:,}.{c:02d}"


def parse_qty(s: str | float | Decimal | None, default: Decimal = Decimal("1")) -> Decimal:
    """Parse a quantity field; default to 1 if blank."""
    if s is None or s == "":
        return default
    try:
        d = Decimal(str(s).strip())
    except Exception:
        return default
    return d
