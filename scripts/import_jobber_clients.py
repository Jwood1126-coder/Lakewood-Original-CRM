"""One-shot importer for the Jobber 'Export Clients' CSV.

Run from the project root:
    python -m scripts.import_jobber_clients <path-to-csv>           # dry-run preview
    python -m scripts.import_jobber_clients <path-to-csv> --commit  # actually write

What it does:
- Groups CSV rows by Jobber client_id (the part of J-ID before the underscore).
- For each unique client → one Client row.
- For each row with a service address → one Property row under that client.
- De-dupes properties by (street1 + city + zip) within a client.
- Auto-fills Ohio county and tax_rate from each property's ZIP.
- Falls back to billing address if service address is blank but billing isn't.
- Wraps the whole thing in one transaction. Audit log captures every insert.

Idempotent-ish: if you re-run, existing Clients (matched by Jobber client_id
stored in `notes`) are skipped to avoid duplicates. So a re-run after adding
new Jobber clients only inserts the new ones.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models.client import Client
from app.models.property import Property
from app.utils.ohio_tax import lookup_county, lookup_rate
from app.utils.phone import normalize_phone


# ---------- helpers ----------

def _norm(s: str | None) -> str:
    return (s or "").strip()


def _multi(s: str | None, sep: str = ";,") -> list[str]:
    """Split on any of `sep` chars and trim. Strips empties."""
    if not s:
        return []
    out = [s]
    for ch in sep:
        out = [piece for chunk in out for piece in chunk.split(ch)]
    return [p.strip() for p in out if p.strip()]


def _first_phone(raw: str | None) -> str | None:
    """Extract the first usable normalized phone from a multi-value field."""
    for piece in _multi(raw, sep=";,"):
        normalized = normalize_phone(piece)
        if normalized:
            return normalized
    return None


def _first_email(raw: str | None) -> str | None:
    """Extract the first email from a multi-value field, lowercased."""
    for piece in _multi(raw, sep=",;"):
        if "@" in piece:
            return piece.lower()
    return None


def _parse_dmy(raw: str | None) -> datetime | None:
    """Jobber dates are DD/MM/YYYY. Return None on failure."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%d/%m/%Y")
    except ValueError:
        return None


def _zip5(raw: str | None) -> str:
    """Return the 5-digit US ZIP from a possibly-formatted string."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    return digits[:5] if digits else ""


def _client_id_from_jid(jid: str) -> str:
    """J-ID is `<clientId>_<propertyId>`. Sometimes propertyId is missing."""
    return (jid or "").split("_", 1)[0].strip()


# ---------- domain shapes ----------

@dataclass
class PropertyImport:
    label: str
    address_line1: str
    address_line2: str
    city: str
    state: str
    zip_code: str
    county: str | None = None
    tax_rate: Decimal | None = None
    jobber_property_id: str | None = None  # so other entities can match by it

    def address_key(self) -> str:
        """Dedup key within a client: normalized street + city + zip."""
        return (
            self.address_line1.strip().lower()
            + "|" + self.city.strip().lower()
            + "|" + self.zip_code
        )


@dataclass
class ClientImport:
    jobber_client_id: str
    name: str
    phone: str | None
    email: str | None
    is_company: bool
    company_name: str
    contact_first: str
    contact_last: str
    lead_source: str
    referred_by: str
    created_at: datetime | None
    properties: list[PropertyImport] = field(default_factory=list)

    def build_notes(self) -> str:
        """Synthesize the notes field from extras Jobber gave us."""
        bits: list[str] = []
        if self.is_company and (self.contact_first or self.contact_last):
            bits.append(f"Contact: {self.contact_first} {self.contact_last}".strip())
        if self.lead_source:
            bits.append(f"Lead source: {self.lead_source}")
        if self.referred_by:
            bits.append(f"Referred by: {self.referred_by}")
        bits.append(f"[Imported from Jobber, client #{self.jobber_client_id}]")
        return "\n".join(bits)


# ---------- parsing ----------

def parse_csv(path: Path) -> list[ClientImport]:
    """Read the CSV, group by Jobber client_id, return one ClientImport per."""
    # Jobber CSVs are usually UTF-8 with BOM
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Group rows by client_id
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cid = _client_id_from_jid(r.get("J-ID", ""))
        if not cid:
            continue
        grouped[cid].append(r)

    clients: list[ClientImport] = []
    for cid, group in grouped.items():
        # Use the first row for client-level details
        first = group[0]
        is_company = (_norm(first.get("Is Company?", "")).lower() == "true")

        display_name = _norm(first.get("Display Name"))
        if not display_name:
            display_name = (
                _norm(first.get("Company Name"))
                or f'{_norm(first.get("First Name"))} {_norm(first.get("Last Name"))}'.strip()
                or f"Unnamed (Jobber #{cid})"
            )

        # Pick the best phone across all rows for this client
        phone: str | None = None
        for r in group:
            for col in ("Main Phone #s", "Mobile Phone #s", "Home Phone #s",
                         "Work Phone #s", "Other Phone #s"):
                phone = _first_phone(r.get(col))
                if phone:
                    break
            if phone:
                break

        # Pick the best email across all rows
        email: str | None = None
        for r in group:
            email = _first_email(r.get("E-mails"))
            if email:
                break

        ci = ClientImport(
            jobber_client_id=cid,
            name=display_name,
            phone=phone,
            email=email,
            is_company=is_company,
            company_name=_norm(first.get("Company Name")),
            contact_first=_norm(first.get("First Name")),
            contact_last=_norm(first.get("Last Name")),
            lead_source=_norm(first.get("Lead Source")),
            referred_by=_norm(first.get("CFT[Referred By]")),
            created_at=_parse_dmy(first.get("Created Date")),
        )

        # Build properties from each row's Service or Billing address
        seen_keys: set[str] = set()
        for i, r in enumerate(group, start=1):
            svc_street = _norm(r.get("Service Street 1"))
            svc_city = _norm(r.get("Service City"))
            svc_zip = _zip5(r.get("Service Zip code"))

            bill_street = _norm(r.get("Billing Street 1"))
            bill_city = _norm(r.get("Billing City"))
            bill_zip = _zip5(r.get("Billing Zip code"))

            if svc_street and svc_city:
                source = "service"
                line1 = svc_street
                line2 = _norm(r.get("Service Street 2"))
                city = svc_city
                state = _norm(r.get("Service State")) or "OH"
                zip_code = svc_zip
            elif bill_street and bill_city:
                source = "billing"
                line1 = bill_street
                line2 = _norm(r.get("Billing Street 2"))
                city = bill_city
                state = _norm(r.get("Billing State")) or "OH"
                zip_code = bill_zip
            else:
                continue  # row has no usable address — skip

            # Normalize state to 2-letter (Jobber gives us "Ohio", we want "OH")
            state2 = _state_to_abbr(state)

            label = _norm(r.get("Service Property Name")) or (
                "Home" if len(group) == 1 else f"Property #{i}"
            )

            prop = PropertyImport(
                label=label,
                address_line1=line1,
                address_line2=line2,
                city=city,
                state=state2,
                zip_code=zip_code or "00000",
            )
            key = prop.address_key()
            if key in seen_keys:
                continue
            seen_keys.add(key)

            # Auto-fill OH county + tax rate from ZIP
            county = lookup_county(prop.zip_code)
            prop.county = county
            prop.tax_rate = Decimal(str(lookup_rate(county)))

            ci.properties.append(prop)

        clients.append(ci)

    return clients


# Minimal US-state name → 2-letter map (Jobber writes the full name)
_STATE_MAP = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC",
}


def _state_to_abbr(state: str) -> str:
    s = (state or "").strip().upper()
    if len(s) == 2:
        return s
    return _STATE_MAP.get(s, "OH")  # fall back to OH for unknowns


# ---------- writing ----------

JOBBER_TAG = "[Imported from Jobber, client #"


def _existing_client_for(cid: str) -> Client | None:
    """Find a previously-imported client by Jobber id (encoded in notes)."""
    return db.session.scalar(
        select(Client).where(Client.notes.like(f"%[Imported from Jobber, client #{cid}]%"))
    )


def write_clients(
    parsed: list[ClientImport],
    commit: bool,
    skip_jobber_ids: set[str] | None = None,
) -> dict:
    skip_jobber_ids = skip_jobber_ids or set()
    stats = {
        "clients_created": 0,
        "clients_skipped_existing": 0,
        "clients_skipped_user_request": 0,
        "properties_created": 0,
        "properties_skipped_dup": 0,
    }
    warnings: list[str] = []

    for ci in parsed:
        if ci.jobber_client_id in skip_jobber_ids:
            stats["clients_skipped_user_request"] += 1
            continue
        existing = _existing_client_for(ci.jobber_client_id)
        if existing is not None:
            stats["clients_skipped_existing"] += 1
            continue

        client = Client(
            name=ci.name,
            phone=ci.phone,
            email=ci.email,
            notes=ci.build_notes(),
            created_at=ci.created_at or datetime.utcnow(),
        )
        db.session.add(client)
        db.session.flush()
        stats["clients_created"] += 1

        for p in ci.properties:
            # Tag the Jobber property ID into notes so the jobs/quotes/
            # invoices syncs can find this property later.
            notes = (f"[Jobber property #{p.jobber_property_id}]"
                     if p.jobber_property_id else None)
            prop = Property(
                client_id=client.id,
                label=p.label,
                address_line1=p.address_line1,
                address_line2=p.address_line2 or None,
                city=p.city,
                state=p.state,
                zip_code=p.zip_code,
                county=p.county,
                tax_rate=p.tax_rate or Decimal("0.0575"),
                notes=notes,
            )
            db.session.add(prop)
            stats["properties_created"] += 1

    if commit:
        db.session.commit()
    else:
        db.session.rollback()

    return {"stats": stats, "warnings": warnings}


# ---------- CLI ----------

def detect_probable_dups(parsed: list[ClientImport]) -> list[tuple[ClientImport, ClientImport]]:
    """Return pairs of clients that look like the same person within ONE CSV.

    Heuristic: same email (case-insensitive) — strongest signal.
    Same name + same phone — also strong.
    Returns the older one (by created_at) first in each pair so the caller
    can recommend keeping the older.
    """
    by_email: dict[str, list[ClientImport]] = {}
    by_name_phone: dict[tuple[str, str], list[ClientImport]] = {}
    for c in parsed:
        if c.email:
            by_email.setdefault(c.email.lower(), []).append(c)
        if c.phone and c.name:
            by_name_phone.setdefault((c.name.lower(), c.phone), []).append(c)

    pairs: list[tuple[ClientImport, ClientImport]] = []
    seen: set[tuple[str, str]] = set()
    for group in list(by_email.values()) + list(by_name_phone.values()):
        if len(group) < 2:
            continue
        group_sorted = sorted(
            group,
            key=lambda c: c.created_at or datetime.min,
        )
        for newer in group_sorted[1:]:
            key = tuple(sorted([group_sorted[0].jobber_client_id,
                                 newer.jobber_client_id]))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((group_sorted[0], newer))
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Path to Jobber Clients CSV")
    parser.add_argument("--commit", action="store_true",
                        help="Actually write to the DB. Without this flag, dry-run only.")
    parser.add_argument(
        "--skip-jobber-ids",
        default="",
        help="Comma-separated Jobber client IDs to skip. "
             "Use this to drop test entries and known duplicates.",
    )
    args = parser.parse_args()

    skip_ids = {s.strip() for s in args.skip_jobber_ids.split(",") if s.strip()}

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"ERROR: file not found: {csv_path}", file=sys.stderr)
        return 2

    parsed = parse_csv(csv_path)
    print(f"\nParsed {len(parsed)} unique clients from {csv_path.name}")
    total_props = sum(len(c.properties) for c in parsed)
    print(f"  {total_props} properties total\n")

    # Surface probable duplicates in the dry-run preview
    dups = detect_probable_dups(parsed)
    if dups:
        print("=" * 60)
        print(f"PROBABLE DUPLICATES ({len(dups)} pairs):")
        print("=" * 60)
        for older, newer in dups:
            why = []
            if older.email and older.email == newer.email:
                why.append(f"same email ({older.email})")
            if older.phone and older.phone == newer.phone:
                why.append(f"same phone ({older.phone})")
            print(f"  {older.name!r}: keep #{older.jobber_client_id}, "
                  f"skip #{newer.jobber_client_id}  ({'; '.join(why)})")
        print()

    # Sample preview (first 5)
    print("=" * 60)
    print("PREVIEW (first 5 clients):")
    print("=" * 60)
    for c in parsed[:5]:
        print(f"\n  {c.name}")
        print(f"    phone: {c.phone or '(none)'}")
        print(f"    email: {c.email or '(none)'}")
        print(f"    properties: {len(c.properties)}")
        for p in c.properties:
            print(f"      - {p.label}: {p.address_line1}, {p.city}, "
                  f"{p.state} {p.zip_code} (county: {p.county or '?'}, "
                  f"tax: {(p.tax_rate or 0)*100:.2f}%)")
    print()

    app = create_app()
    with app.app_context():
        result = write_clients(parsed, commit=args.commit, skip_jobber_ids=skip_ids)

    print("=" * 60)
    if args.commit:
        print("✓ COMMITTED to database.")
    else:
        print("DRY RUN — nothing was written. Pass --commit to actually import.")
    print("=" * 60)
    for k, v in result["stats"].items():
        print(f"  {k}: {v}")
    for w in result["warnings"]:
        print(f"  ⚠ {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
