"""FastAPI server — thin routing layer over ApiService, Auth, Notification."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response

from .api_service import (
    ApiService, ConflictError, PermissionDeniedError, QuotaExceededError,
)
from .auth import get_current_user, login, register
from .block_server import BlockServer
from .config import DriveConfig
from .database import Database
from .models import (
    AuthResponse, BlockUploadRequest, BlockUploadResponse,
    CommitRequest, CommitResponse, LoginRequest, RegisterRequest,
    ResolveRequest, ResolveResponse, SessionStatusResponse,
    ShareRequest, StatsResponse, SyncRequest, SyncResponse,
    UploadStartRequest, UploadStartResponse,
)
from .notification import NotificationCenter
from .object_store import ObjectStore

# Shared state (initialized in lifespan)
_config: DriveConfig | None = None
_db: Database | None = None
_service: ApiService | None = None
_notifier: NotificationCenter | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config, _db, _service, _notifier
    _config = DriveConfig()
    _db = Database(_config)
    await _db.initialize()
    store = ObjectStore(_config)
    bs = BlockServer(_config, store)
    _notifier = NotificationCenter(_db)
    _service = ApiService(_config, _db, bs, store, _notifier)
    yield
    await _db.close()


app = FastAPI(title="Google Drive System", lifespan=lifespan)


def get_service() -> ApiService:
    return _service


def get_notifier() -> NotificationCenter:
    return _notifier


# ─── Auth Endpoints ───────────────────────────────────────────────────

@app.post("/api/register", response_model=AuthResponse)
async def api_register(req: RegisterRequest):
    user_id = await register(_db, req.email, req.password)
    token = await login(_db, req.email, req.password)
    return AuthResponse(token=token, user_id=user_id)


@app.post("/api/login", response_model=AuthResponse)
async def api_login(req: LoginRequest):
    token = await login(_db, req.email, req.password)
    if not token:
        raise HTTPException(401, "Invalid credentials")
    from .auth import _tokens
    user_id = _tokens[token]
    return AuthResponse(token=token, user_id=user_id)


# ─── File Listing ─────────────────────────────────────────────────────

@app.get("/api/files/list")
async def api_list_files(user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    return await svc.list_files(user_id)


# ─── Upload ───────────────────────────────────────────────────────────

@app.post("/api/files/upload", response_model=UploadStartResponse)
async def api_start_upload(req: UploadStartRequest, user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    try:
        session_id, file_id, dedup = await svc.start_upload(
            user_id, req.file_name, req.path, req.size, req.total_block_count,
            file_id=req.file_id, base_version=req.base_version, block_hashes=req.block_hashes,
        )
        return UploadStartResponse(session_id=session_id, file_id=file_id, deduplicated_hashes=dedup)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.post("/api/blocks", response_model=BlockUploadResponse)
async def api_upload_blocks(req: BlockUploadRequest, user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    try:
        received = await svc.upload_blocks(req.session_id, [{"hash": b.hash, "data_b64": b.data_b64} for b in req.blocks])
        return BlockUploadResponse(received_hashes=received)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/sessions/{session_id}", response_model=SessionStatusResponse)
async def api_session_status(session_id: str, user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    try:
        status = await svc.get_session_status(session_id)
        return SessionStatusResponse(**status)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.post("/api/files/{file_id}/commit", response_model=CommitResponse)
async def api_commit(file_id: str, req: CommitRequest, user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    try:
        version_no = await svc.commit(user_id, req.session_id, file_id, req.block_hashes)
        return CommitResponse(file_id=file_id, version_no=version_no)
    except QuotaExceededError:
        raise HTTPException(413, "Storage quota exceeded")
    except ConflictError as e:
        raise HTTPException(409, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


# ─── Download ─────────────────────────────────────────────────────────

@app.get("/api/files/{file_id}/download")
async def api_download(file_id: str, version: Optional[int] = None,
                       user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    try:
        data = await svc.download(user_id, file_id, version)
        file_info = await _db.get_file(file_id)
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{file_info["name"]}"'},
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionDeniedError:
        raise HTTPException(403, "Access denied")


# ─── Revisions ────────────────────────────────────────────────────────

@app.get("/api/files/{file_id}/revisions")
async def api_revisions(file_id: str, user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    return await svc.list_revisions(file_id)


# ─── Sync ─────────────────────────────────────────────────────────────

@app.post("/api/sync", response_model=SyncResponse)
async def api_sync(req: SyncRequest, user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    states = [{"file_id": s.file_id, "base_version": s.base_version, "block_hashes": s.block_hashes} for s in req.states]
    result = await svc.sync(user_id, states)
    return SyncResponse(**result)


# ─── Resolve ──────────────────────────────────────────────────────────

@app.post("/api/files/{file_id}/resolve", response_model=ResolveResponse)
async def api_resolve(file_id: str, req: ResolveRequest, user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    try:
        new_version = await svc.resolve(user_id, file_id, req.action, req.block_hashes)
        return ResolveResponse(file_id=file_id, new_version_no=new_version)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ─── Share ────────────────────────────────────────────────────────────

@app.post("/api/files/{file_id}/share")
async def api_share(file_id: str, req: ShareRequest, user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    try:
        await svc.share(user_id, file_id, req.shared_with, req.permission)
        return {"status": "ok"}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionDeniedError:
        raise HTTPException(403, "Only owner can share")


# ─── Notifications ────────────────────────────────────────────────────

@app.get("/api/notifications")
async def api_notifications(wait: float = Query(30.0), since: int = Query(0),
                            user_id: str = Depends(get_current_user)):
    notifier = get_notifier()
    events = await notifier.poll(user_id, since_id=since, wait=min(wait, 60.0))
    return events


# ─── Admin / Stats ────────────────────────────────────────────────────

@app.post("/api/admin/gc")
async def api_gc(user_id: str = Depends(get_current_user)):
    svc: ApiService = get_service()
    freed = await svc.garbage_collect()
    return {"freed_blocks": freed}


@app.get("/api/stats", response_model=StatsResponse)
async def api_stats():
    svc: ApiService = get_service()
    stats = await svc.get_stats()
    return StatsResponse(**stats)
