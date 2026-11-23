# -*- coding: utf-8 -*-
"""Безопасность: хеширование паролей и JWT."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os

from jose import JWTError, jwt

from .settings import settings

# ---------------------------------------------------------------------------
# Пароли (PBKDF2-HMAC-SHA256, без внешних зависимостей)
# ---------------------------------------------------------------------------

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(subject: str, role: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def create_agent_token(agent_id: str) -> str:
    """Долгоживущий токен агента (упрощённая модель доверия)."""
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": agent_id,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(days=3650)).timestamp()),
        "type": "agent",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
