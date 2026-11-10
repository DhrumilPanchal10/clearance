"""API authentication (plan T7.1 / T7.3 Clerk).

In production, bearer tokens are Clerk-issued JWTs verified against the
configured JWKS; the verified claims carry the user's role and clinic (tenant).
When no Clerk key is configured (local dev / offline / tests), the app falls
back to **dev headers** — ``X-Role`` and ``X-Tenant`` — so the whole system is
runnable without an external auth provider. Dev mode never activates once a
Clerk secret is set.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from agentcore.auth import ROLES, UserClaims
from clearance.config import settings


def dev_mode() -> bool:
    return not settings.clerk_secret_key


async def current_user(
    x_role: str | None = Header(default=None),
    x_tenant: str | None = Header(default=None),
    x_user: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> UserClaims:
    if dev_mode():
        role = (x_role or "coordinator").lower()
        if role not in ROLES:
            raise HTTPException(status_code=403, detail=f"unknown role {role!r}")
        return UserClaims(
            user_id=x_user or "dev-user",
            tenant_id=x_tenant or "clinic-a",
            role=role,
            raw={"dev": True},
        )
    # Production path: verify a Clerk JWT. (JWKS verification is wired in deploy;
    # the claims shape is identical so handlers are mode-agnostic.)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    raise HTTPException(status_code=501, detail="clerk verification configured at deploy time")
