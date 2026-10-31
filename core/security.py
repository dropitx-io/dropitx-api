"""JWT validation, API key utilities, and password hashing."""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import bcrypt
import httpx
from jose import jwt, JWTError, JWSError

from core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Firebase ID token and session cookie verification (public x509 certs, cached)
# ---------------------------------------------------------------------------

_CERTS_TTL = 3600  # 1 hour
# A kid miss refetches the certs to survive key rotation, at most this often per
# key set, so tokens with made-up kids cannot turn into outbound requests.
_CERTS_REFETCH_MIN_INTERVAL = 60
# After a failed fetch the endpoint is not called again for this long: callers get the
# cached certs (or an immediate error when none are cached) instead of each waiting
# out the fetch timeout.
_CERTS_FAILURE_BACKOFF = 30
_CLOCK_SKEW_SECONDS = 60


@dataclass
class _TokenKind:
    """A kind of Firebase JWT we trust: its issuer, signing keys and cert cache."""

    name: str
    issuer_prefix: str
    certs_url: str
    certs: dict[str, str] | None = None
    certs_expire_at: float = 0.0
    last_fetch_at: float = 0.0
    last_failure_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


# The unverified `iss` claim only picks the entry whose keys verify the
# signature. The signature plus the exact verified `iss`/`aud` authorize.
_TOKEN_KINDS = (
    _TokenKind(
        name="ID token",
        issuer_prefix="https://securetoken.google.com/",
        certs_url=(
            "https://www.googleapis.com/robot/v1/metadata/x509/"
            "securetoken@system.gserviceaccount.com"
        ),
    ),
    _TokenKind(
        name="session cookie",
        issuer_prefix="https://session.firebase.google.com/",
        certs_url="https://www.googleapis.com/identitytoolkit/v3/relyingparty/publicKeys",
    ),
)


def _fetch_certs(kind: _TokenKind, force: bool = False) -> dict[str, str]:
    """Fetch and cache a kind's public x509 signing certs, keyed by kid.

    `force` asks for a refetch before the TTL runs out; it is honored only once
    `_CERTS_REFETCH_MIN_INTERVAL` has passed since the last fetch.

    When the fetch fails, cached certs keep being served (stale) rather than failing
    every login, and the endpoint is left alone for `_CERTS_FAILURE_BACKOFF`. With
    nothing cached the `httpx.HTTPError` propagates.
    """
    with kind.lock:
        now = time.time()
        if kind.certs is not None:
            if force:
                if now - kind.last_fetch_at < _CERTS_REFETCH_MIN_INTERVAL:
                    return kind.certs
            elif now < kind.certs_expire_at:
                return kind.certs

        if kind.last_failure_at and now - kind.last_failure_at < _CERTS_FAILURE_BACKOFF:
            if kind.certs is not None:
                return kind.certs
            raise httpx.TransportError(f"{kind.name} signing certs unavailable (recent fetch failed)")

        try:
            resp = httpx.get(kind.certs_url, timeout=10)
            resp.raise_for_status()
            certs = resp.json()
        except httpx.HTTPError as exc:
            kind.last_failure_at = time.time()
            if kind.certs is None:
                raise
            logger.warning("Fetching %s signing certs failed, serving cached certs: %s", kind.name, exc)
            return kind.certs

        kind.certs = certs
        kind.certs_expire_at = now + _CERTS_TTL
        kind.last_fetch_at = now
        kind.last_failure_at = 0.0
        return kind.certs


def _cert_for_kid(kind: _TokenKind, kid: str) -> str:
    """PEM cert for a kid, refetching once on a miss to handle key rotation."""
    certs = _fetch_certs(kind)
    if kid not in certs:
        certs = _fetch_certs(kind, force=True)
    cert = certs.get(kid)
    if not cert:
        raise ValueError(f"No matching Firebase signing cert for kid={kid}")
    return cert


def _kind_for_issuer(issuer: object) -> _TokenKind:
    if isinstance(issuer, str):
        for kind in _TOKEN_KINDS:
            if issuer.startswith(kind.issuer_prefix):
                return kind
    raise ValueError("Untrusted token issuer")


def _require_past_time(payload: dict, claim: str) -> None:
    value = payload.get(claim)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Token missing or invalid {claim!r} claim")
    if value > time.time() + _CLOCK_SKEW_SECONDS:
        raise ValueError(f"Token {claim!r} is in the future")


def verify_firebase_jwt(token: str) -> dict:
    """Verify a Firebase ID token or session cookie and return its claims.

    Validates the RS256 signature against the public certs for the token's
    kind plus the audience/issuer for the configured project, and the
    exp/iat/auth_time/sub claims. Returns a dict with at least 'sub' (the
    Firebase uid). Raises ValueError on any invalid/expired token.
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

        kind = _kind_for_issuer(jwt.get_unverified_claims(token).get("iss"))
        cert = _cert_for_kid(kind, kid)

        payload = jwt.decode(
            token,
            cert,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"{kind.issuer_prefix}{project_id}",
            options={"require_exp": True, "require_aud": True, "require_iss": True, "require_iat": True},
        )
    except (JWTError, JWSError) as exc:
        raise ValueError(f"Invalid Firebase token: {exc}") from exc

    _require_past_time(payload, "iat")
    _require_past_time(payload, "auth_time")
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
