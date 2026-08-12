"""JWT validation, API key utilities, and password hashing."""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timezone

import bcrypt
from jose import jwt, JWTError, JWSError

from core.config import settings

# ---------------------------------------------------------------------------
# Firebase ID token verification (public x509 certs, cached)
# ---------------------------------------------------------------------------

_FIREBASE_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)
_FIREBASE_ISSUER_PREFIX = "https://securetoken.google.com/"

_CERTS_CACHE: dict[str, str] | None = None
_CERTS_EXPIRES: float = 0.0
_CERTS_TTL = 3600  # 1 hour; refetched on a kid miss to survive key rotation


def _fetch_firebase_certs(force: bool = False) -> dict[str, str]:
    """Fetch and cache Firebase's public x509 signing certs, keyed by kid."""
    global _CERTS_CACHE, _CERTS_EXPIRES

    now = time.time()
    if not force and _CERTS_CACHE is not None and now < _CERTS_EXPIRES:
        return _CERTS_CACHE

    import httpx

    resp = httpx.get(_FIREBASE_CERTS_URL, timeout=10)
    resp.raise_for_status()
    _CERTS_CACHE = resp.json()
    _CERTS_EXPIRES = now + _CERTS_TTL
    return _CERTS_CACHE


def _cert_for_kid(kid: str) -> str:
    """PEM cert for a kid, refetching once on a miss to handle key rotation."""
    certs = _fetch_firebase_certs()
    if kid not in certs:
        certs = _fetch_firebase_certs(force=True)
    cert = certs.get(kid)
    if not cert:
        raise ValueError(f"No matching Firebase signing cert for kid={kid}")
    return cert


def verify_firebase_jwt(token: str) -> dict:
    """Verify a Firebase ID token and return its claims.

    Validates the RS256 signature against Firebase's public certs plus the
    audience/issuer for the configured project. Returns a dict with at least
    'sub' (the Firebase uid). Raises ValueError on any invalid/expired token.
    """
    project_id = settings.firebase_project_id
    if not project_id:
        raise ValueError("FIREBASE_PROJECT_ID is not configured")

    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise ValueError(f"Unexpected alg {header.get('alg')!r}, expected RS256")
        kid = header.get("kid")
        if not kid:
            raise ValueError("Token header missing 'kid'")

        cert = _cert_for_kid(kid)

        payload = jwt.decode(
            token,
            cert,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"{_FIREBASE_ISSUER_PREFIX}{project_id}",
        )
    except (JWTError, JWSError) as exc:
        raise ValueError(f"Invalid Firebase ID token: {exc}") from exc

    if not payload.get("sub"):
        raise ValueError("Token missing 'sub' (uid) claim")
    return payload


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
