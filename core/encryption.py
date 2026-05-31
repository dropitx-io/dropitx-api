"""E2E encryption utilities — AES-256-GCM + PBKDF2 key derivation.

Zero-knowledge model: server never sees plaintext keys.
- Client encrypts with random key → server stores encrypted blob
- Key lives in URL fragment (#key), never sent to server
- Optional password layer: PBKDF2 derives key from password + salt
"""

from __future__ import annotations

import base64
import os
from typing import NamedTuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KEY_LEN = 32          # 256 bits
_IV_LEN = 12           # 96 bits (recommended for AES-GCM)
_SALT_LEN = 16         # 128 bits
_PBKDF2_ITERATIONS = 600_000  # OWASP 2024 recommendation for PBKDF2-SHA256


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class EncryptionResult(NamedTuple):
    """Result of encrypting data."""
    ciphertext: bytes       # encrypted blob (includes GCM tag)
    iv: str                 # base64url-encoded IV
    salt: str | None        # base64url-encoded salt (None if no password)


class KeyBundle(NamedTuple):
    """A generated encryption key + IV for client-side use."""
    key: str                # base64url-encoded 256-bit key
    iv: str                 # base64url-encoded 96-bit IV
    salt: str               # base64url-encoded 128-bit salt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64encode(data: bytes) -> str:
    """URL-safe base64 encode (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(s: str) -> bytes:
    """URL-safe base64 decode (adds padding back)."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


# ---------------------------------------------------------------------------
# Key generation (for client-side use)
# ---------------------------------------------------------------------------

def generate_encryption_key() -> KeyBundle:
    """Generate a random AES-256 key + IV + salt for E2E encryption.

    Returns base64url-encoded values suitable for:
    - Sending to the client (Web Crypto API import)
    - Storing IV/salt on the server (key stays client-side only)
    """
    key = os.urandom(_KEY_LEN)
    iv = os.urandom(_IV_LEN)
    salt = os.urandom(_SALT_LEN)
    return KeyBundle(
        key=_b64encode(key),
        iv=_b64encode(iv),
        salt=_b64encode(salt),
    )


def generate_iv() -> str:
    """Generate a random IV, base64url-encoded."""
    return _b64encode(os.urandom(_IV_LEN))


def generate_salt() -> str:
    """Generate a random salt, base64url-encoded."""
    return _b64encode(os.urandom(_SALT_LEN))


# ---------------------------------------------------------------------------
# Password-based key derivation (PBKDF2)
# ---------------------------------------------------------------------------

def derive_key_from_password(password: str, salt: str) -> bytes:
    """Derive a 256-bit AES key from a password + salt using PBKDF2-SHA256.

    Args:
        password: plaintext password
        salt: base64url-encoded salt

    Returns:
        32-byte derived key
    """
    salt_bytes = _b64decode(salt)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=salt_bytes,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


# ---------------------------------------------------------------------------
# AES-256-GCM encrypt / decrypt (server-side)
# ---------------------------------------------------------------------------

def encrypt_data(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """Encrypt data with AES-256-GCM.

    Args:
        plaintext: data to encrypt
        key: 32-byte AES key
        iv: 12-byte IV (must be unique per key)

    Returns:
        ciphertext with appended GCM authentication tag
    """
    aesgcm = AESGCM(key)
    return aesgcm.encrypt(iv, plaintext, None)


def decrypt_data(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt AES-256-GCM ciphertext.

    Args:
        ciphertext: encrypted data with GCM tag
        key: 32-byte AES key
        iv: 12-byte IV used during encryption

    Returns:
        decrypted plaintext

    Raises:
        cryptography.exceptions.InvalidTag: if key/iv/ciphertext mismatch
    """
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext, None)


# ---------------------------------------------------------------------------
# High-level: encrypt with password
# ---------------------------------------------------------------------------

def encrypt_with_password(plaintext: bytes, password: str) -> EncryptionResult:
    """Encrypt data with a password using PBKDF2 + AES-256-GCM.

    Returns encrypted blob + IV + salt (all base64url-encoded in result).
    The password never leaves the caller — only derived key is used.
    """
    salt = os.urandom(_SALT_LEN)
    iv = os.urandom(_IV_LEN)
    key = derive_key_from_password(password, _b64encode(salt))
    ciphertext = encrypt_data(plaintext, key, iv)
    return EncryptionResult(
        ciphertext=ciphertext,
        iv=_b64encode(iv),
        salt=_b64encode(salt),
    )


def decrypt_with_password(
    ciphertext: bytes, password: str, iv_b64: str, salt_b64: str
) -> bytes:
    """Decrypt data that was encrypted with encrypt_with_password().

    Args:
        ciphertext: encrypted blob
        password: plaintext password
        iv_b64: base64url-encoded IV
        salt_b64: base64url-encoded salt

    Returns:
        decrypted plaintext
    """
    key = derive_key_from_password(password, salt_b64)
    iv = _b64decode(iv_b64)
    return decrypt_data(ciphertext, key, iv)


# ---------------------------------------------------------------------------
# URL fragment helpers
# ---------------------------------------------------------------------------

def build_share_url_with_key(base_url: str, slug: str, encryption_key: str) -> str:
    """Build a share URL with the encryption key in the fragment.

    Format: https://dropitx.com/s/{slug}#{encryption_key}
    The fragment is never sent to the server — zero-knowledge model.
    """
    return f"{base_url}/s/{slug}#{encryption_key}"


def extract_key_from_url(url: str) -> str | None:
    """Extract the encryption key from a share URL fragment.

    Returns None if no fragment is present.
    """
    if "#" in url:
        return url.split("#", 1)[1]
    return None
