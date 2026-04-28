"""Lakewood Original — services and service area.

Sourced from lakewoodoriginal.com. Update these here when the website
changes; everything in the app reads from this single file.
"""
from __future__ import annotations

# Service categories shown on the website.
SERVICES = [
    {
        "key": "woodworking",
        "label": "Woodworking & Carpentry",
        "examples": "Decks, porches, shelves, steps, garden beds",
    },
    {
        "key": "doors_hardware",
        "label": "Doors, Hardware & Fixtures",
        "examples": "Interior doors, closet repairs, hardware swaps, lighting",
    },
    {
        "key": "kitchen_bath",
        "label": "Kitchen & Bath Updates",
        "examples": "Plumbing fixes, faucet/vanity/lighting upgrades",
    },
    {
        "key": "assembly",
        "label": "Assembly Services",
        "examples": "Exercise equipment, outdoor furniture, storage racks",
    },
    {
        "key": "installation",
        "label": "Installation & Mounting",
        "examples": "TVs, shelves, ceiling fans, smart devices",
    },
    {
        "key": "other",
        "label": "Something else",
        "examples": "Tell us about it",
    },
]

SERVICE_BY_KEY = {s["key"]: s for s in SERVICES}

# Cities we cover (per the website). Used to validate intake addresses
# and to show in the public form's city dropdown.
SERVICE_AREA_CITIES = [
    "Lakewood",
    "Rocky River",
    "Westlake",
    "Cleveland",          # West Cleveland → Cleveland for ZIP-lookup purposes
    "Parma",
    "Parma Heights",
    "Avon",
    "Berea",
    "North Royalton",
    "Strongsville",
    "Broadview Heights",
    "Brecksville",
    "Olmsted Falls",
]


def is_in_service_area(city: str | None) -> bool:
    if not city:
        return False
    norm = city.strip().lower()
    return any(c.lower() == norm for c in SERVICE_AREA_CITIES) or "cleveland" in norm
