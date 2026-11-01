"""Custom domains endpoints for teams — add, verify, configure brand."""

from __future__ import annotations

import asyncio
import logging
import secrets
import dns.resolver
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies import User, get_current_user, get_client_ip
from app.dashboard.team_helpers import require_team_member, resolve_team_by_slug
from core.rate_limit import check_domain_resolve_rate_limit, rate_limit_exceeded
from core.supabase import get_admin_client
from models.domain import AddDomainInput, UpdateDomainBrandInput, DomainVerificationStatus

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERIFICATION_PREFIX = "_dropitx-verify"
EXPECTED_CNAME_TARGET = "dropitx.com"


def _generate_verification_token() -> str:
    """Generate a 32-byte hex token for domain verification."""
    return secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Domain CRUD
# ---------------------------------------------------------------------------

@router.post("/teams/{slug}/domains", status_code=201, tags=["Custom Domains"])
async def add_domain(
    slug: str,
    body: AddDomainInput,
    user: User = Depends(get_current_user),
):
    """Add a custom domain to a team. Requires owner role.

    Returns the domain record with a TXT verification token.
    The team must configure a TXT record:
        _dropitx-verify.<domain> → <verification_token>
    """
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="owner")

    domain = body.domain.lower().strip()
    client = get_admin_client()

    # Check if domain already exists globally
    existing = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .select("id")
        .eq("domain", domain)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="Domain already registered")

    # Check domain limit per team (2 for pro)
    team_domains = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .select("id")
        .eq("team_id", team["id"])
        .execute()
    )
    if team["plan"] == "free" and team_domains.data:
        raise HTTPException(
            status_code=403,
            detail="Custom domains require Pro plan. Upgrade at /dashboard/billing",
        )
    if team["plan"] == "pro" and len(team_domains.data or []) >= 2:
        raise HTTPException(
            status_code=403,
            detail="Pro plan allows up to 2 custom domains",
        )

    verification_token = _generate_verification_token()

    resp = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .insert({
            "team_id": team["id"],
            "domain": domain,
            "status": "pending",
            "verification_token": verification_token,
        })
        .execute()
    )
    domain_row = resp.data[0]

    return {
        **domain_row,
        "instructions": {
            "txt_record": {
                "name": f"{VERIFICATION_PREFIX}.{domain}",
                "value": verification_token,
                "ttl": 300,
            },
            "cname_record": {
                "name": domain,
                "value": EXPECTED_CNAME_TARGET,
                "ttl": 300,
            },
        },
    }


@router.get("/teams/{slug}/domains", tags=["Custom Domains"])
async def list_domains(
    slug: str,
    user: User = Depends(get_current_user),
):
    """List all custom domains for a team."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"])

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .select("*")
        .eq("team_id", team["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


@router.get("/teams/{slug}/domains/{domain_id}", tags=["Custom Domains"])
async def get_domain(
    slug: str,
    domain_id: str,
    user: User = Depends(get_current_user),
):
    """Get a specific custom domain's details."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"])

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .select("*")
        .eq("id", domain_id)
        .eq("team_id", team["id"])
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Domain not found")
    return resp.data[0]


@router.delete("/teams/{slug}/domains/{domain_id}", status_code=204, tags=["Custom Domains"])
async def remove_domain(
    slug: str,
    domain_id: str,
    user: User = Depends(get_current_user),
):
    """Remove a custom domain from a team. Owner only."""
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="owner")

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .delete()
        .eq("id", domain_id)
        .eq("team_id", team["id"])
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Domain not found")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@router.post("/teams/{slug}/domains/{domain_id}/verify", tags=["Custom Domains"])
async def verify_domain(
    slug: str,
    domain_id: str,
    user: User = Depends(get_current_user),
) -> DomainVerificationStatus:
    """Trigger DNS verification for a custom domain.

    Checks for TXT record: _dropitx-verify.<domain> → <token>
    On success, updates status to 'active'.
    """
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="owner")

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .select("*")
        .eq("id", domain_id)
        .eq("team_id", team["id"])
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Domain not found")

    domain_record = resp.data[0]
    domain_name = domain_record["domain"]
    expected_token = domain_record["verification_token"]

    if not expected_token:
        raise HTTPException(status_code=400, detail="No verification token set")

    # Check TXT record
    txt_record_name = f"{VERIFICATION_PREFIX}.{domain_name}"
    verified = False
    verification_error = None

    try:
        answers = dns.resolver.resolve(txt_record_name, "TXT")
        for rdata in answers:
            for txt_string in rdata.strings:
                if txt_string.decode() == expected_token:
                    verified = True
                    break
            if verified:
                break
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        verification_error = f"TXT record not found. Add {txt_record_name} → {expected_token}"
    except dns.resolver.NoNameservers:
        verification_error = "DNS resolution failed — no nameservers responded"
    except Exception as e:
        verification_error = f"DNS lookup failed: {str(e)}"

    if verified:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(
            lambda: client.table("custom_domains")
            .update({
                "status": "active",
                "verified_at": now,
                "ssl_status": "pending",  # Will be provisioned by background job
            })
            .eq("id", domain_id)
            .execute()
        )
        return DomainVerificationStatus(
            domain=domain_name,
            status="active",
            txt_record=expected_token,
            verified_at=datetime.fromisoformat(now),
            ssl_status="pending",
            ssl_issued_at=None,
            message="Domain verified successfully! SSL certificate will be provisioned shortly.",
        )
    else:
        await asyncio.to_thread(
            lambda: client.table("custom_domains")
            .update({"status": "verifying"})
            .eq("id", domain_id)
            .execute()
        )
        return DomainVerificationStatus(
            domain=domain_name,
            status="verifying",
            txt_record=expected_token,
            verified_at=None,
            ssl_status="pending",
            ssl_issued_at=None,
            message=verification_error or "Verification pending. Ensure TXT record is configured correctly.",
        )


# ---------------------------------------------------------------------------
# Brand customization
# ---------------------------------------------------------------------------

@router.patch("/teams/{slug}/domains/{domain_id}/brand", tags=["Custom Domains"])
async def update_domain_brand(
    slug: str,
    domain_id: str,
    body: UpdateDomainBrandInput,
    user: User = Depends(get_current_user),
):
    """Update brand customization for a custom domain (logo, color, favicon).

    Only active domains can be customized.
    """
    team = await resolve_team_by_slug(slug)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await require_team_member(user.id, team["id"], min_role="owner")

    client = get_admin_client()

    # Check domain exists and is active
    resp = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .select("*")
        .eq("id", domain_id)
        .eq("team_id", team["id"])
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Domain not found")

    domain_record = resp.data[0]
    if domain_record["status"] != "active":
        raise HTTPException(
            status_code=400,
            detail="Domain must be verified and active before brand customization",
        )

    updates = {}
    if body.brand_logo_url is not None:
        updates["brand_logo_url"] = body.brand_logo_url
    if body.brand_color is not None:
        updates["brand_color"] = body.brand_color
    if body.brand_favicon_url is not None:
        updates["brand_favicon_url"] = body.brand_favicon_url

    if not updates:
        return domain_record

    resp = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .update(updates)
        .eq("id", domain_id)
        .execute()
    )
    return resp.data[0]


# ---------------------------------------------------------------------------
# Public resolution (for reverse proxy)
# ---------------------------------------------------------------------------

@router.get("/domains/resolve/{domain}", tags=["Custom Domains"], include_in_schema=False)
async def resolve_custom_domain(domain: str, request: Request):
    """Internal endpoint to resolve a custom domain to its team configuration.

    Used by reverse proxy to route requests to the correct team.
    Not exposed in public API docs.
    Rate-limited 60/min per IP (fail-open) — this endpoint is designed for
    internal reverse-proxy use only but is now reachable from the public
    internet via the Cloudflare Tunnel.
    """
    ip = get_client_ip(request)
    rate = check_domain_resolve_rate_limit(ip)
    if not rate.success:
        raise rate_limit_exceeded(rate)

    client = get_admin_client()
    resp = await asyncio.to_thread(
        lambda: client.table("custom_domains")
        .select("*, teams!team_id(id, slug, name, plan)")
        .eq("domain", domain.lower())
        .eq("status", "active")
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Domain not configured")

    record = resp.data[0]
    return {
        "team_id": record["team_id"],
        "team_slug": record["teams"]["slug"],
        "team_name": record["teams"]["name"],
        "brand_logo_url": record.get("brand_logo_url"),
        "brand_color": record.get("brand_color"),
        "brand_favicon_url": record.get("brand_favicon_url"),
    }
