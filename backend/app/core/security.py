"""Password hashing, JWT issuing/verification and ticket QR signing.

Argon2id is used for passwords (memory-hard, the current OWASP recommendation).
JWTs are short-lived access tokens plus opaque, DB-backed refresh tokens -- the
refresh token is stored only as a hash so a database leak cannot be replayed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings
from app.core.errors import AuthenticationError

_hasher = PasswordHasher(time_cost=2, memory_cost=64 * 1024, parallelism=2)

TokenType = Literal["access", "refresh"]


# ------------------------------------------------------------- passwords ---
def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except (InvalidHashError, ValueError):
        return True


# ------------------------------------------------------------------ jwt ---
def create_access_token(
    subject: uuid.UUID | str,
    *,
    role: str,
    extra: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Your session has expired. Please sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid authentication token.") from exc
    if payload.get("typ") != "access":
        raise AuthenticationError("Invalid token type.")
    return payload


# -------------------------------------------------------- refresh tokens ---
def generate_refresh_token() -> tuple[str, str]:
    """Return ``(plaintext, sha256_hex)``. Only the hash is ever persisted."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ------------------------------------------------------- ticket QR codes ---
def sign_ticket_payload(booking_reference: str, booking_id: uuid.UUID) -> str:
    """Produce a tamper-evident QR payload: ``ref.booking_id.signature``.

    Without the signature anyone could print a ticket with a guessed reference.
    The gate scanner verifies the MAC before it even hits the database.
    """
    body = f"{booking_reference}.{booking_id}"
    mac = hmac.new(
        settings.ticket_qr_secret.encode(), body.encode(), hashlib.sha256
    ).digest()
    sig = base64.urlsafe_b64encode(mac).decode().rstrip("=")[:32]
    return f"{body}.{sig}"


def verify_ticket_payload(payload: str) -> tuple[str, uuid.UUID]:
    try:
        reference, booking_id_str, _sig = payload.split(".")
    except ValueError as exc:
        raise AuthenticationError("Malformed ticket payload.") from exc

    booking_id = uuid.UUID(booking_id_str)
    expected = sign_ticket_payload(reference, booking_id)
    if not hmac.compare_digest(expected, payload):
        raise AuthenticationError("Ticket signature is invalid.")
    return reference, booking_id


# ------------------------------------------------------------------ misc ---
_REF_ALPHABET = "ACDEFGHJKLMNPQRSTUVWXYZ2345679"  # no I/O/0/1/8/B -- unambiguous


def generate_booking_reference(prefix: str = "CN") -> str:
    """Human-quotable booking reference, e.g. ``CN7QK4M2XR``."""
    body = "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))
    return f"{prefix}{body}"
