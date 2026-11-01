"""Firebase auth session endpoint — provisions the user and returns the profile."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_firebase_claims
from core.supabase import get_admin_client
from core.usernames import assign_username

logger = logging.getLogger(__name__)

router = APIRouter()


class SessionProfile(BaseModel):
    id: str
    email: str | None = None
    email_verified: bool = False
    profile: dict


@router.get("/session", tags=["Auth"], summary="Provision user and return profile")
async def get_session(claims: dict = Depends(get_firebase_claims)) -> SessionProfile:
    uid = claims["sub"]
    email = claims.get("email")

    client = get_admin_client()
    try:
        resp = await asyncio.to_thread(
            lambda: client.rpc(
                "provision_firebase_user", {"p_uid": uid, "p_email": email}
            ).execute()
        )
    except Exception as exc:
        logger.error("Provisioning failed for %s: %s", uid, exc)
        raise HTTPException(status_code=500, detail="Provisioning failed") from exc

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=500, detail="Provisioning returned no profile")
    profile = rows[0]

    # Every user gets a public handle; existing users without one get it here, lazily.
    if not profile.get("username"):
        try:
            profile = {**profile, "username": await asyncio.to_thread(
                assign_username, client, uid, email, profile.get("display_name") or claims.get("name"),
            )}
        except Exception:
            logger.warning("Username assignment failed for %s", uid, exc_info=True)

    return SessionProfile(
        id=uid,
        email=email,
        email_verified=bool(claims.get("email_verified")),
        profile=profile,
    )
