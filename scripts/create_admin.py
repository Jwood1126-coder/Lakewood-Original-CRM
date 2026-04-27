"""Create or reset the admin user.

Usage (local):
    python -m scripts.create_admin
        Creates admin from ADMIN_EMAIL / ADMIN_PASSWORD env vars.
        If user exists, resets the password.

    python -m scripts.create_admin --email you@x.com --password 'whatever'
        Override env values.

Run this once after the first deploy / migration.
"""
from __future__ import annotations

import argparse
import secrets
import sys

from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models.user import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument(
        "--display-name", default=None, help="Optional friendly name"
    )
    parser.add_argument(
        "--only-if-missing",
        action="store_true",
        help="Skip silently if any User already exists. Used in release step "
             "so deploys don't reset the password every time.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        # If --only-if-missing and any user exists, do nothing.
        if args.only_if_missing:
            from sqlalchemy import func
            count = db.session.scalar(select(func.count(User.id))) or 0
            if count > 0:
                print(f"Admin bootstrap skipped: {count} user(s) already exist")
                return 0

        email = (args.email or app.config["ADMIN_EMAIL"]).strip().lower()
        password = args.password or app.config["ADMIN_PASSWORD"]

        generated = False
        if not password:
            password = secrets.token_urlsafe(16)
            generated = True

        user = db.session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, display_name=args.display_name)
            user.set_password(password)
            db.session.add(user)
            action = "Created"
        else:
            user.set_password(password)
            if args.display_name:
                user.display_name = args.display_name
            action = "Updated"

        db.session.commit()
        print(f"{action} user: {email}")
        if generated:
            print()
            print("=" * 60)
            print(f"  GENERATED PASSWORD: {password}")
            print("  Save this NOW. It is not shown again.")
            print("  Sign in then change it from /auth/change-password.")
            print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
