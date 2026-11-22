"""Argon2 password hashing, JWT token management, and Tutor Access Code."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from shared.config import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXPIRY_HOURS,
    TUTOR_CODE_PATH,
    DATA_DIR,
)

ph = PasswordHasher()


# ── Password Hashing ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a password using Argon2."""
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its Argon2 hash."""
    try:
        return ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# ── JWT Tokens ───────────────────────────────────────────────────────────────

def create_access_token(user_id: int, role: str, email: str) -> str:
    """Create a JWT access token."""
    payload = {
        "sub": str(user_id),
        "role": role,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token. Returns payload or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


# ── Tutor Access Code ────────────────────────────────────────────────────────

def generate_tutor_access_code() -> str:
    """Generate a 6-character alphanumeric tutor access code."""
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(6))


def get_or_create_tutor_access_code() -> str:
    """Read tutor access code from file, or generate and save a new one."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if TUTOR_CODE_PATH.exists():
        code = TUTOR_CODE_PATH.read_text().strip()
        if len(code) == 6:
            return code
    code = generate_tutor_access_code()
    TUTOR_CODE_PATH.write_text(code)
    return code
