"""Usernames: the public handle in /u/{username}.

3-30 characters of lowercase letters, digits and hyphens, starting and ending with
a letter or digit, unique across users, and never a word the frontend routes on.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from asyncpg.exceptions import UniqueViolationError

MIN_LENGTH = 3
MAX_LENGTH = 30
RESERVED_USERNAMES = frozenset({"admin", "api", "dashboard", "auth", "s", "u", "embed"})

_PATTERN = re.compile(rf"^[a-z0-9][a-z0-9-]{{{MIN_LENGTH - 2},{MAX_LENGTH - 2}}}[a-z0-9]$")
_NOT_ALLOWED = re.compile(r"[^a-z0-9]+")
_FALLBACK = "user"
# Taken names are skipped up front; this bounds the retries when others take names meanwhile.
_MAX_ATTEMPTS = 20


def validate_username(name: str) -> str | None:
    """Why `name` cannot be a username, or None when it can."""
    if not _PATTERN.match(name):
        return (
            f"Username must be {MIN_LENGTH}-{MAX_LENGTH} lowercase letters, digits or hyphens, "
            "starting and ending with a letter or digit"
        )
    if name in RESERVED_USERNAMES:
        return "Username is reserved"
    return None


def _slugify(text: str | None) -> str:
    return _NOT_ALLOWED.sub("-", (text or "").lower()).strip("-")[:MAX_LENGTH].rstrip("-")


def derive_username_base(email: str | None, display_name: str | None) -> str:
    """A username-shaped name from the email's local part, else the display name, else 'user'."""
    local_part = email.split("@", 1)[0] if email else None
    for source in (local_part, display_name):
        base = _slugify(source)
        if len(base) >= MIN_LENGTH:
            return base
    return _FALLBACK


def username_candidates(base: str) -> Iterator[str]:
    """`base`, then base2, base3, ... cut so each stays within MAX_LENGTH; never a reserved word."""
    if validate_username(base) is None:
        yield base
    n = 2
    while True:
        suffix = str(n)
        candidate = base[: MAX_LENGTH - len(suffix)].rstrip("-") + suffix
        if validate_username(candidate) is None:
            yield candidate
        n += 1


def assign_username(client, user_id: str, email: str | None, display_name: str | None) -> str | None:
    """Give the user a unique username if their profile has none; return the username they end up with.

    Sync (run it in a thread). Only a profile whose username is still NULL is written,
    so a concurrent call or an earlier choice is never overwritten.
    """
    base = derive_username_base(email, display_name)
    rows = client.table("user_profiles").select("username").like("username", f"{base}%").execute().data
    taken = {row["username"] for row in rows or []}
    free = (c for c in username_candidates(base) if c not in taken)
    for _, candidate in zip(range(_MAX_ATTEMPTS), free):
        try:
            updated = (
                client.table("user_profiles")
                .update({"username": candidate})
                .eq("user_id", user_id)
                .is_("username", None)
                .execute()
                .data
            )
        except UniqueViolationError:
            continue
        if updated:
            return updated[0]["username"]
        break
    current = client.table("user_profiles").select("username").eq("user_id", user_id).execute().data
    return current[0]["username"] if current else None
