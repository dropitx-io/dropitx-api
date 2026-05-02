"""FastAPI dependencies — placeholders, implemented in Phase 2."""


async def get_current_user():
    """Extract and validate Supabase JWT from Authorization header."""
    raise NotImplementedError("Phase 2")


async def get_api_key():
    """Validate Bearer API key (shk_/sht_ prefix)."""
    raise NotImplementedError("Phase 2")


async def get_optional_user():
    """Optional JWT auth — returns user or None."""
    raise NotImplementedError("Phase 2")
