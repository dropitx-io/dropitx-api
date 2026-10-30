"""E2E Encryption endpoints for shares.

Provides:
- POST /shares/{slug}/encrypt — encrypt an existing share with a password
- POST /shares/{slug}/reencrypt — re-encrypt with a new password (double protection)
- GET  /shares/{slug}/encryption-info — get encryption metadata for a share
- POST /encryption/generate-key — generate a new encryption key bundle (for client-side use)
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.dependencies import User, get_client_ip, get_current_user, get_optional_user
from app.public._share_auth import authorize_owner
from core.encryption import (
    _b64decode,
    _b64encode,
    build_share_url_with_key,
    decrypt_with_password,
    derive_key_from_password,
    encrypt_data,
    encrypt_with_password,
    generate_encryption_key,
    generate_iv,
    generate_salt,
)
from core.rate_limit import check_password_rate_limit, check_public_read_rate_limit
from core.supabase import get_admin_client

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class EncryptShareRequest(BaseModel):
    """Encrypt an existing (unencrypted) share with a password."""
    password: str = Field(min_length=1, max_length=128, description="Password to encrypt with")
    delete_token: str | None = None


class ReencryptShareRequest(BaseModel):
    """Re-encrypt an encrypted share with a new password (double protection)."""
    old_password: str = Field(min_length=1, max_length=128, description="Current password")
    new_password: str = Field(min_length=1, max_length=128, description="New password")
    delete_token: str | None = None


class EncryptionInfoResponse(BaseModel):
    """Encryption metadata for a share."""
    encrypted: bool
    encryption_iv: str | None = None
    encryption_salt: str | None = None
    has_password: bool = False


class KeyBundleResponse(BaseModel):
    """Generated encryption key bundle for client-side use."""
    key: str = Field(description="Base64url-encoded 256-bit AES key")
    iv: str = Field(description="Base64url-encoded 96-bit IV")
    salt: str = Field(description="Base64url-encoded 128-bit salt")


class EncryptResponse(BaseModel):
    """Response after encrypting a share."""
    slug: str
    encrypted: bool = True
    encryption_iv: str
    encryption_salt: str
    share_url: str = Field(description="Share URL with encryption key in fragment")
    detail: str = "Share encrypted successfully"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_share_for_encrypt(slug: str) -> dict:
    """Fetch a share row by slug. Raises 404 if not found."""
    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("shares")
        .select("*")
        .eq("slug", slug)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Share not found")
    return rows[0]


# ---------------------------------------------------------------------------
# POST /encryption/generate-key — generate key bundle for client
# ---------------------------------------------------------------------------

@router.post(
    "/encryption/generate-key",
    tags=["Encryption"],
    summary="Generate encryption key bundle",
)
async def generate_key_endpoint():
    """Generate a random AES-256-GCM key + IV + salt for client-side encryption.

    The key is returned once — the client uses it to encrypt data before upload.
    Only IV and salt are stored on the server; the key stays in the URL fragment.
    """
    bundle = generate_encryption_key()
    return KeyBundleResponse(key=bundle.key, iv=bundle.iv, salt=bundle.salt)


# ---------------------------------------------------------------------------
# GET /shares/{slug}/encryption-info
# ---------------------------------------------------------------------------

@router.get(
    "/shares/{slug}/encryption-info",
    tags=["Encryption"],
    summary="Get share encryption info",
)
async def get_encryption_info(slug: str, request: Request):
    """Return encryption metadata for a share (IV, salt, password status).

    Does NOT return any keys — zero-knowledge model.
    """
    ip = get_client_ip(request)
    rate = check_public_read_rate_limit(ip)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    row = await _fetch_share_for_encrypt(slug)
    return EncryptionInfoResponse(
        encrypted=row.get("encrypted", False),
        encryption_iv=row.get("encryption_iv"),
        encryption_salt=row.get("encryption_salt"),
        has_password=bool(row.get("password_hash")),
    )


# ---------------------------------------------------------------------------
# POST /shares/{slug}/encrypt — encrypt existing share with password
# ---------------------------------------------------------------------------

@router.post(
    "/shares/{slug}/encrypt",
    tags=["Encryption"],
    summary="Encrypt share with password",
    response_model=EncryptResponse,
)
async def encrypt_share(
    slug: str,
    body: EncryptShareRequest,
    user: User | None = Depends(get_optional_user),
):
    """Encrypt an existing unencrypted share with a password.

    Flow:
    1. Fetches the share's plaintext content from storage
    2. Derives AES-256 key from password via PBKDF2
    3. Encrypts content with AES-256-GCM
    4. Overwrites the storage blob with encrypted content
    5. Updates share metadata (encrypted, iv, salt)
    6. Also sets the share as password-protected

    Returns the share URL — caller should append the encryption key fragment.
    """
    row = await _fetch_share_for_encrypt(slug)

    if user is None and not body.delete_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    authorize_owner(row, user, body.delete_token)

    if row.get("encrypted"):
        raise HTTPException(
            status_code=400,
            detail="Share is already encrypted. Use /reencrypt to change password.",
        )

    client = get_admin_client()

    # Fetch current plaintext content from storage
    storage_path = row["storage_path"]
    source = row.get("source", "")
    bucket = "html-files" if source in ("upload", "editor") else "shares"

    try:
        resp = await asyncio.to_thread(
            lambda: client.storage.from_(bucket).download(storage_path),
        )
        plaintext = resp if isinstance(resp, bytes) else str(resp).encode("utf-8")
    except Exception as exc:
        logger.error("Failed to download content for encryption: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read share content") from exc

    # Encrypt with password
    result = encrypt_with_password(plaintext, body.password)

    # Upload encrypted blob back to storage
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_(bucket).update(
                storage_path,
                result.ciphertext,
                file_options={"content-type": "application/octet-stream", "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("Failed to upload encrypted content: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to store encrypted content") from exc

    # Update share metadata
    from core.security import hash_password
    update_data = {
        "encrypted": True,
        "encryption_iv": result.iv,
        "encryption_salt": result.salt,
        "password_hash": hash_password(body.password),
        "content_text": None,  # Clear searchable plaintext
    }
    await asyncio.to_thread(
        lambda: client.table("shares")
        .update(update_data)
        .eq("id", row["id"])
        .execute()
    )

    # Build share URL
    from core.config import settings
    share_url = f"{settings.frontend_url}/s/{slug}"

    logger.info("Share %s encrypted with password", slug)

    return EncryptResponse(
        slug=slug,
        encryption_iv=result.iv,
        encryption_salt=result.salt,
        share_url=share_url,
    )


# ---------------------------------------------------------------------------
# POST /shares/{slug}/reencrypt — re-encrypt with new password
# ---------------------------------------------------------------------------

@router.post(
    "/shares/{slug}/reencrypt",
    tags=["Encryption"],
    summary="Re-encrypt share with new password",
    response_model=EncryptResponse,
)
async def reencrypt_share(slug: str, request: Request, body: ReencryptShareRequest):
    """Re-encrypt an encrypted share with a new password.

    Decrypts with old password, re-encrypts with new password.
    Useful for password rotation or adding double protection.
    """
    ip = get_client_ip(request)
    rate = check_password_rate_limit(ip, slug)
    if not rate.success:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again later.",
            headers={"Retry-After": str(max(rate.reset, 1))},
        )

    row = await _fetch_share_for_encrypt(slug)

    if not row.get("encrypted"):
        raise HTTPException(
            status_code=400,
            detail="Share is not encrypted. Use /encrypt first.",
        )

    client = get_admin_client()
    storage_path = row["storage_path"]
    source = row.get("source", "")
    bucket = "html-files" if source in ("upload", "editor") else "shares"

    # Fetch encrypted content
    try:
        resp = await asyncio.to_thread(
            lambda: client.storage.from_(bucket).download(storage_path),
        )
        ciphertext = resp if isinstance(resp, bytes) else str(resp).encode("utf-8")
    except Exception as exc:
        logger.error("Failed to download encrypted content: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to read encrypted content") from exc

    # Decrypt with old password
    try:
        plaintext = decrypt_with_password(
            ciphertext,
            body.old_password,
            row["encryption_iv"],
            row["encryption_salt"],
        )
    except Exception as exc:
        logger.warning("Decryption failed during re-encrypt for %s: %s", slug, exc)
        raise HTTPException(status_code=401, detail="Incorrect old password") from exc

    # Re-encrypt with new password
    result = encrypt_with_password(plaintext, body.new_password)

    # Upload re-encrypted blob
    try:
        await asyncio.to_thread(
            lambda: client.storage.from_(bucket).update(
                storage_path,
                result.ciphertext,
                file_options={"content-type": "application/octet-stream", "upsert": "true"},
            ),
        )
    except Exception as exc:
        logger.error("Failed to upload re-encrypted content: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to store re-encrypted content") from exc

    # Update metadata
    from core.security import hash_password
    update_data = {
        "encryption_iv": result.iv,
        "encryption_salt": result.salt,
        "password_hash": hash_password(body.new_password),
    }
    await asyncio.to_thread(
        lambda: client.table("shares")
        .update(update_data)
        .eq("id", row["id"])
        .execute()
    )

    from core.config import settings
    share_url = f"{settings.frontend_url}/s/{slug}"

    logger.info("Share %s re-encrypted with new password", slug)

    return EncryptResponse(
        slug=slug,
        encryption_iv=result.iv,
        encryption_salt=result.salt,
        share_url=share_url,
    )
