"""HTTP layer for /api/auth/* and /api/users/* (spec 4.2).

Domain exceptions from service.py become status codes here, so the business
layer never imports fastapi.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth import service
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.auth.schemas import (BanRequest, LoginRequest, RefreshRequest,
                              RegisterRequest, RoleUpdateRequest, TokenPair,
                              UserOut)

logger = logging.getLogger(__name__)

router = APIRouter()

_admin = require_role("admin")


@router.post("/api/auth/register", status_code=201)
async def register(req: RegisterRequest):
    """Returns the user only - no tokens (spec 4.2); the client logs in next."""
    try:
        return {"user": await service.register(
            req.username, req.email, req.password)}
    except service.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/auth/login", response_model=TokenPair)
async def login(req: LoginRequest):
    try:
        return await service.login(req.email, req.password)
    except service.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except service.PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/api/auth/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest):
    try:
        return await service.refresh(req.refresh_token)
    except service.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/api/auth/logout", status_code=204)
async def logout(user: CurrentUser = Depends(get_current_user)):
    await service.logout(user.id)
    return Response(status_code=204)


@router.get("/api/auth/me", response_model=UserOut)
async def me(user: CurrentUser = Depends(get_current_user)):
    try:
        return await service.get_me(user.id)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/users")
async def list_users(_: CurrentUser = Depends(_admin),
                     limit: int = Query(50, ge=1, le=100),
                     offset: int = Query(0, ge=0)):
    return await service.list_users(limit, offset)


@router.get("/api/users/{user_id}")
async def get_user(user_id: str):
    """Public projection: {id, username, role}."""
    try:
        return await service.get_public_user(user_id)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/api/users/{user_id}/role", response_model=UserOut)
async def change_role(user_id: str, req: RoleUpdateRequest,
                      actor: CurrentUser = Depends(_admin)):
    try:
        return await service.set_role(actor.id, user_id, req.role)
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/users/{user_id}/ban", response_model=UserOut)
async def ban_user(user_id: str,
                   actor: CurrentUser = Depends(_admin),
                   req: BanRequest | None = None):
    try:
        return await service.ban(actor.id, user_id, req.reason if req else "")
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/users/{user_id}/unban", response_model=UserOut)
async def unban_user(user_id: str, _: CurrentUser = Depends(_admin)):
    try:
        return await service.unban(user_id)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
