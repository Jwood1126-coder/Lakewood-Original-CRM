"""Symmetric encryption for at-rest secrets (OAuth tokens etc.).

Why we encrypt: Jobber access tokens are bearer credentials — anyone with
the plaintext can call the Jobber API as Jake. Plain DB rows are visible
to anyone with shell access to the Railway volume. Encrypting at rest
means even a leaked SQLite snapshot doesn't compromise the integration.

Key derivation: HKDF-SHA256 over Flask's SECRET_KEY with a fixed salt +
"jobber-token-v1" info string. Rotating SECRET_KEY invalidates stored
tokens (you'd reconnect Jobber).

Format: Fernet (AES-128-CBC + HMAC-SHA256, RFC-conformant).
"""
from __future__ import annotations

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app


# Stable salt — the SECRET_KEY provides the entropy; salt only ensures
# the same SECRET_KEY produces a different key for different *purposes*.
_SALT = b"lakewood-original-crm-fernet-v1"


def _fernet() -> Fernet:
    secret = current_app.config.get("SECRET_KEY", "")
    if not secret or secret == "dev-only-do-not-use-in-prod":
        raise RuntimeError(
            "SECRET_KEY is missing or default. Refusing to encrypt with "
            "predictable key. Set SECRET_KEY in env."
        )
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=b"jobber-token-v1",
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_str(plaintext: str) -> str:
    """Returns a URL-safe base64 string suitable for storing in a TEXT column."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_str(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
