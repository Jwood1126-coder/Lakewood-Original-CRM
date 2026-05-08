"""User model — operator login. v1 has exactly one user (you)."""
from __future__ import annotations

from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask_login import UserMixin
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

_hasher = PasswordHasher()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    theme: Mapped[str] = mapped_column(String(20), nullable=False, default="dark")
    accent: Mapped[str] = mapped_column(String(20), nullable=False, default="amber")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- Password handling ---

    def set_password(self, raw: str) -> None:
        self.password_hash = _hasher.hash(raw)

    def verify_password(self, raw: str) -> bool:
        try:
            _hasher.verify(self.password_hash, raw)
        except VerifyMismatchError:
            return False
        # Re-hash if argon2 parameters have been upgraded
        if _hasher.check_needs_rehash(self.password_hash):
            self.password_hash = _hasher.hash(raw)
        return True

    def __repr__(self) -> str:
        return f"<User {self.email}>"
