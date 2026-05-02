"""Slug and token generation using cryptographically secure random."""

import secrets
import string

# Alphanumeric alphabet for slugs (no ambiguous chars: 0/O, 1/l/I)
_SLUG_ALPHABET = string.ascii_lowercase + string.digits


def generate_slug() -> str:
    """Generate a 10-char random alphanumeric slug for share URLs."""
    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(10))


def generate_delete_token() -> str:
    """Generate a 32-char hex token for share deletion."""
    return secrets.token_hex(16)
