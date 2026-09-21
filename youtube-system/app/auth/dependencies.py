"""FastAPI dependencies: Bearer token -> CurrentUser (spec 4.1).

Uses the native HTTPBearer scheme so Swagger UI renders an Authorize button.
"""
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import security
from app.auth.security import InvalidTokenError

_bearer = HTTPBearer(auto_error=False)

# Redis handle injected from the api-server lifespan (the SAME client passed to
# service.bind_redis). get_current_user uses it for a single O(1) EXISTS check
# of the ban marker (spec 2.5).
_redis = None


def bind_redis(client) -> None:
    global _redis
    _redis = client


@dataclass
class CurrentUser:
    """Fields come from the JWT payload - no DB lookup. A banned user is
    rejected by get_current_user via a Redis marker (immediate, spec 2.5);
    only *role changes* still wait for the access token to be refreshed."""

    id: str
    username: str
    role: str


def _parse(creds: HTTPAuthorizationCredentials | None) -> CurrentUser | None:
    if creds is None or creds.scheme.lower() != "bearer":
        return None
    try:
        payload = security.decode_access_token(creds.credentials)
    except InvalidTokenError:
        return None
    return CurrentUser(
        id=payload["sub"],
        username=payload.get("username", ""),
        role=payload.get("role", "user"),
    )


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    user = _parse(creds)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    # One O(1) Redis EXISTS (no DB) makes a ban revoke even a live access token
    # immediately (spec 2.5). Guard on _redis so the module imports cleanly in
    # route-table checks that never bind a client.
    if _redis is not None and await _redis.exists(security.ban_key(user.id)):
        raise HTTPException(status_code=403, detail="account is banned")
    return user


async def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser | None:
    """For public endpoints: parse if present, never fail."""
    return _parse(creds)


def require_role(min_role: str) -> Callable:
    """Dependency factory enforcing ROLE_LEVEL[user.role] >= ROLE_LEVEL[min_role].

    Unknown roles (e.g. a value written by hand into the DB) are denied.
    """
    need = security.ROLE_LEVEL[min_role]

    async def _require(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if security.ROLE_LEVEL.get(user.role, 0) < need:
            raise HTTPException(
                status_code=403, detail=f"requires {min_role} role or above")
        return user

    return _require
