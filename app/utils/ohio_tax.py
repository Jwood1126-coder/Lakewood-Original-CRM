"""Ohio sales tax — county rates and ZIP→county lookup.

Source: Ohio Department of Taxation, sales tax rates effective 2025-Q4.
Update this table annually. The state portion is 5.75%; counties piggyback
0% to 2.25% on top.

Rates stored as Decimal fractions (0.0800 = 8.00%). Per-property tax_rate
defaults from this table; per-invoice override available in Phase 3.

NOT EXHAUSTIVE — this is a curated set covering the populated counties + a
handful around Cleveland area where Jake likely operates. Add others as
customers come from new counties. Unknown ZIPs fall back to DEFAULT_COUNTY
config.
"""
from __future__ import annotations

from decimal import Decimal

# County name -> total combined tax rate (state + county)
# State portion is 5.75% (0.0575); county piggyback varies.
COUNTY_RATES: dict[str, Decimal] = {
    # Major metro
    "Cuyahoga": Decimal("0.0800"),     # Cleveland
    "Franklin": Decimal("0.0750"),     # Columbus
    "Hamilton": Decimal("0.0725"),     # Cincinnati
    "Summit": Decimal("0.0675"),       # Akron
    "Lucas": Decimal("0.0725"),        # Toledo
    "Montgomery": Decimal("0.0750"),   # Dayton
    "Stark": Decimal("0.0650"),        # Canton
    "Lorain": Decimal("0.0675"),
    "Lake": Decimal("0.0725"),
    "Geauga": Decimal("0.0675"),
    "Medina": Decimal("0.0675"),
    "Portage": Decimal("0.0725"),
    "Mahoning": Decimal("0.0750"),
    "Trumbull": Decimal("0.0675"),
    "Butler": Decimal("0.0650"),
    "Warren": Decimal("0.0700"),
    "Clermont": Decimal("0.0675"),
    "Greene": Decimal("0.0675"),
    "Miami": Decimal("0.0700"),
    "Clark": Decimal("0.0750"),
    "Licking": Decimal("0.0725"),
    "Delaware": Decimal("0.0700"),
    "Fairfield": Decimal("0.0675"),
    "Wood": Decimal("0.0675"),
    "Allen": Decimal("0.0685"),
    "Richland": Decimal("0.0700"),
    "Ashtabula": Decimal("0.0700"),
    "Wayne": Decimal("0.0700"),
    "Erie": Decimal("0.0675"),
    "Sandusky": Decimal("0.0725"),
    # ... add more as needed
}

# ZIP code -> county (selected; expand on demand)
# Focused on Cleveland metro since that's likely the operator's region.
ZIP_TO_COUNTY: dict[str, str] = {
    # Cuyahoga County (Cleveland & inner-ring suburbs)
    **{z: "Cuyahoga" for z in (
        "44101", "44102", "44103", "44104", "44105", "44106", "44107", "44108",
        "44109", "44110", "44111", "44112", "44113", "44114", "44115", "44116",
        "44117", "44118", "44119", "44120", "44121", "44122", "44123", "44124",
        "44125", "44126", "44127", "44128", "44129", "44130", "44131", "44132",
        "44133", "44134", "44135", "44136", "44137", "44138", "44139", "44140",
        "44141", "44142", "44143", "44144", "44145", "44146", "44147", "44149",
    )},
    # Lake County
    **{z: "Lake" for z in ("44060", "44077", "44081", "44094", "44095", "44081")},
    # Lorain County
    **{z: "Lorain" for z in ("44035", "44052", "44053", "44054", "44055", "44074")},
    # Geauga County
    **{z: "Geauga" for z in ("44021", "44022", "44023", "44024", "44026", "44062", "44065")},
    # Medina County
    **{z: "Medina" for z in ("44212", "44233", "44235", "44251", "44253", "44254", "44256", "44273", "44275", "44280", "44281")},
    # Summit County (Akron)
    **{z: "Summit" for z in ("44067", "44087", "44203", "44210", "44211", "44216", "44221", "44222", "44223", "44224", "44232", "44236", "44240", "44241", "44260", "44262", "44264", "44272", "44278", "44286", "44301", "44302", "44303", "44304", "44305", "44306", "44307", "44308", "44310", "44311", "44312", "44313", "44314", "44319", "44320")},
    # Portage County
    **{z: "Portage" for z in ("44201", "44231", "44234", "44243", "44260", "44266", "44272")},
    # Franklin (Columbus)
    **{z: "Franklin" for z in ("43004", "43017", "43026", "43054", "43068", "43081", "43085", "43109", "43110", "43119", "43123", "43125", "43137", "43147", "43201", "43202", "43203", "43204", "43205", "43206", "43207", "43209", "43210", "43211", "43212", "43213", "43214", "43215", "43216", "43217", "43218", "43219", "43220", "43221", "43222", "43223", "43224", "43227", "43228", "43229", "43230", "43231", "43232", "43235", "43240")},
    # Hamilton (Cincinnati)
    **{z: "Hamilton" for z in ("45202", "45203", "45204", "45205", "45206", "45207", "45208", "45209", "45211", "45212", "45213", "45214", "45215", "45216", "45217", "45218", "45219", "45220", "45223", "45224", "45225", "45226", "45227", "45229", "45230", "45231", "45232", "45233", "45236", "45237", "45238", "45239", "45243", "45248")},
}


def lookup_county(zip_code: str | None) -> str | None:
    """Return county name for a ZIP, or None if not in our table."""
    if not zip_code:
        return None
    z = zip_code.strip()[:5]
    return ZIP_TO_COUNTY.get(z)


def lookup_rate(county: str | None, default: Decimal = Decimal("0.0575")) -> Decimal:
    """Return tax rate for a county, defaulting to state-only (5.75%)."""
    if not county:
        return default
    return COUNTY_RATES.get(county, default)


def rate_for_zip(zip_code: str | None) -> tuple[str | None, Decimal]:
    """Convenience: ZIP → (county, rate). Returns (None, state-only) if unknown."""
    county = lookup_county(zip_code)
    return county, lookup_rate(county)
