"""JWT validation, API key utilities, and password hashing."""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timezone

import bcrypt
from jose import jwt, JWTError, JWSError
from jose.utils import base64url_decode

from core.config import settings

# ---------------------------------------------------------------------------
# JWKS cache for Supabase JWT verification
# ---------------------------------------------------------------------------

_JWKS_CACHE: dict | None = None
_JWKS_EXPIRES: float = 0.0
_JWKS_TTL = 600  # 10 minutes


def _fetch_jwks() -> dict:
    """Fetch and cache JWKS from Supabase Auth."""
    global _JWKS_CACHE, _JWKS_EXPIRES

    now = time.time()
    if _JWKS_CACHE is not None and now < _JWKS_EXPIRES:
        return _JWKS_CACHE

    import httpx

    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    resp = httpx.get(jwks_url, timeout=10)
    resp.raise_for_status()
    _JWKS_CACHE = resp.json()
    _JWKS_EXPIRES = now + _JWKS_TTL
    return _JWKS_CACHE


def verify_supabase_jwt(token: str) -> dict:
    """Verify a Supabase JWT and return the payload.

    Returns dict with at least 'sub' (user_id).
    Raises ValueError on invalid/expired token.
    """
    try:
        jwks = _fetch_jwks()
        # Extract kid from unverified header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        # Find matching key in JWKS
        rsa_key = {}
        for key in jwks.get("keys", []):
            if key["kid"] == kid:
                rsa_key = key
                break

        if not rsa_key:
            raise ValueError(f"No matching JWKS key for kid={kid}")

        # Decode and verify using the public key from JWKS
        # Supports both RS256 (RSA) and ES256 (ECDSA) algorithms
        alg = rsa_key.get("alg", "RS256")
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=[alg, "RS256", "ES256"],
            options={"verify_aud": False, "verify_at_hash": False},
        )
        return payload

    except JWTError as exc:
        raise ValueError(f"Invalid JWT: {exc}") from exc


# ---------------------------------------------------------------------------
# API key utilities
# ---------------------------------------------------------------------------

# Valid prefixes: shk_ = personal, sht_ = team
_VALID_PREFIXES = ("shk_", "sht_")


def hash_api_key(key: str) -> str:
    """SHA-256 hex digest of an API key."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key(prefix: str) -> tuple[str, str]:
    """Generate an API key with the given prefix.

    Returns (raw_key, hashed_key).
    Valid prefixes: 'shk_' (personal), 'sht_' (team).
    """
    if prefix not in _VALID_PREFIXES:
        raise ValueError(f"Invalid prefix '{prefix}'. Must be one of {_VALID_PREFIXES}")

    raw_suffix = secrets.token_hex(24)  # 48 hex chars
    raw_key = f"{prefix}{raw_suffix}"
    return raw_key, hash_api_key(raw_key)


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------

_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Hash a password with bcrypt (12 rounds)."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())
