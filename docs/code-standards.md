# Code Standards

## File Naming

- **Kebab-case** for all file names
- Descriptive names that convey purpose (e.g., `document_helpers.py`, `team_invites.py`)
- Single responsibility per file — keep under 200 LOC

## Python Conventions

- Python 3.12+ features: type hints (`|` union, `dict | None`), `from __future__ import annotations`
- Use `from __future__ import annotations` at top of every module for forward-reference support
- Type all function signatures and return types
- Use `logging` module (never `print`)
- Use f-strings, never `%` or `.format()`

## Import Order

1. Standard library
2. Third-party packages
3. Local modules (`core.*`, `app.*`, `models.*`)

Separate each group with a blank line.

## Module Organization

```
# Docstring — single-line purpose
"""JWT validation, API key utilities, and password hashing."""

from __future__ import annotations

# Standard library
import hashlib
import secrets

# Third-party
import bcrypt
from jose import jwt

# Local
from core.config import settings

# ---------------------------------------------------------------------------
# Section comment (dashes)
# ---------------------------------------------------------------------------

def function_name(param: str) -> str:
    """Docstring for public functions — single sentence purpose."""
    ...
```

## FastAPI Patterns

### Route Organization
- Routes grouped by auth type in subdirectories (`v1/`, `dashboard/`, `internal/`, `public/`)
- Each subdirectory has a `router.py` that re-exports the parent router
- Tag all routers for OpenAPI grouping

### Dependency Injection
- Auth dependencies defined in `app/dependencies.py`
- Use `Depends(get_current_user)` for JWT-required endpoints
- Use `Depends(get_optional_user)` for optional JWT endpoints
- Use `Depends(get_api_key)` for API key endpoints
- Return Pydantic response models via `response_model` parameter

### Request/Response Models
- Inline Pydantic models in route files for simple DTOs (minimize cross-file imports)
- Shared models in `models/` for cross-route use
- Use `Field()` for validation constraints (min_length, max_length, pattern)

### Error Handling
- Raise `HTTPException` with specific status codes and detail messages
- Catch `Exception` broadly at route level, log with `logger.error`, re-raise as 500
- Never expose internal errors to clients — always return generic messages
- Use `logger.warning` for non-critical failures (storage cleanup, rate limit RPC)

```python
try:
    resp = await asyncio.to_thread(lambda: client.table("shares").insert(data).execute())
except Exception as exc:
    logger.error("Insert failed for slug=%s: %s", slug, exc)
    raise HTTPException(status_code=500, detail="Failed to create share") from exc
```

### Async Patterns
- All Supabase client calls wrapped in `asyncio.to_thread()` — the client is synchronous
- Use `lambda` wrappers to defer evaluation:
  ```python
  await asyncio.to_thread(lambda: client.table("shares").select("*").execute())
  ```
- Fire-and-forget tasks via `asyncio.create_task()` for non-critical updates (e.g., `last_used_at`)

### Compensating Transactions
When a multi-step operation (storage + DB) fails partway:
1. Catch the failure
2. Attempt cleanup of the succeeded step
3. Log cleanup failures as warnings
4. Raise the original error

```python
try:
    await db_insert(...)
except Exception as exc:
    await cleanup_storage(path)  # best-effort
    raise HTTPException(...) from exc
```

## Database Patterns

### Supabase Client Usage
- Use `get_admin_client()` in all route handlers (bypasses RLS)
- Use `get_user_client(token)` only when RLS should apply
- Never store or log service-role key

### RPCs
Use Postgres RPCs for complex operations that need atomicity or are expensive in client code:
- Rate limiting (`check_rate_limit`)
- Search with ranking (`search_shares`)
- Multi-table mutations (`create_team_invite`, `accept_team_invite`)

## Security Standards

### Authentication
- JWT: Verified against Supabase JWKS (RS256, audience = Supabase URL)
- API keys: SHA-256 hashed in DB, never stored in plaintext
- Passwords: bcrypt with 12 rounds

### Authorization
- Team roles: `owner (3) > editor (2) > viewer (1)` — numeric comparison
- Route-level: check auth before accessing any data
- Resource-level: verify ownership or membership before modification

### Rate Limiting
- All public mutation endpoints rate-limited
- Password unlock: fail-closed (reject on RPC failure)
- Analytics/upload: fail-open (allow on RPC failure)
- Return `Retry-After` header when rate limited

### Input Validation
- All user input validated via Pydantic models
- File type checking via MIME type + extension fallback
- Content size limits enforced at application level
- Slug generation uses cryptographically secure random

## Logging

- Module-level logger: `logger = logging.getLogger(__name__)`
- Error-level for failures that affect the request
- Warning-level for non-critical failures (best-effort cleanup)
- Debug-level for auth failures (avoid noise)
- Never log secrets, tokens, passwords, or service-role keys
