"""FastAPI application exposing the upload + video management API."""
import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from app import database
from app import presign
from app.auth import security
from app.auth import service as auth_service
from app.auth import dependencies as auth_deps
from app.auth.dependencies import CurrentUser, get_current_user, get_optional_user, require_role
from app.auth.router import router as auth_router
from app.comments.router import router as comments_router
from app.moderation.router import router as moderation_router
from app.moderation import service as moderation_service
from app import drm
from app.completion_consumer import run_consumer
from app.config import config
from app.models import UploadUrlRequest, UploadUrlResponse, VideoCreateRequest
from app.presign import PresignError, ext_of
from app.queue import create_client, push_task

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

redis = None
consumer_task = None
consumer_stop = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis, consumer_task
    os.makedirs(config.original_dir, exist_ok=True)
    os.makedirs(config.transcoded_dir, exist_ok=True)
    await database.init_db()
    await auth_service.ensure_seed_users()
    redis = create_client()
    auth_service.bind_redis(redis)
    auth_deps.bind_redis(redis)
    consumer_stop.clear()
    consumer_task = asyncio.create_task(run_consumer(consumer_stop))
    logger.info("API server started")
    yield
    consumer_stop.set()
    if consumer_task:
        consumer_task.cancel()
    await redis.aclose()
    logger.info("API server stopped")


app = FastAPI(title="YouTube Video Streaming System", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(comments_router)
app.include_router(moderation_router)
app.include_router(drm.router)


def _card(v: dict) -> dict:
    uploader = ({"id": v["uploader_id"], "username": v.get("uploader_username")}
                if v.get("uploader_id") else None)
    return {
        "id": v["id"],
        "title": v["title"],
        "description": v["description"],
        "status": v["status"],
        "moderation_status": v.get("moderation_status", "approved"),
        "rejection_reason": v.get("rejection_reason"),
        "duration_sec": v["duration_sec"],
        "thumbnail_url": f"/media/{v['id']}/thumbnail.jpg"
                         if v["status"] == "ready" else None,
        "uploader": uploader,
        "created_at": v["created_at"],
    }


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(req: UploadUrlRequest,
                            user: CurrentUser = Depends(require_role("creator"))):
    try:
        return presign.issue(req.filename, req.size, user.id)
    except PresignError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/upload/{token}")
async def upload_binary(token: str, request: Request):
    info = presign.consume(token)
    if info is None:
        raise HTTPException(status_code=403, detail="Invalid or expired upload token")

    video_id = info["video_id"]
    ext = ext_of(request.query_params.get("filename", "video.mp4"))
    if ext not in config.allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported extension .{ext}")

    original_dir = os.path.join(config.original_dir, video_id)
    os.makedirs(original_dir, exist_ok=True)
    dest = os.path.join(original_dir, f"original.{ext}")

    written = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                written += len(chunk)
                if written > config.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail="File exceeds 1GB limit")
                f.write(chunk)
    except HTTPException:
        shutil.rmtree(original_dir, ignore_errors=True)
        raise
    if written == 0:
        shutil.rmtree(original_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Empty upload")

    return {"video_id": video_id, "bytes": written, "path": dest}


@app.post("/api/videos")
async def create_video(req: VideoCreateRequest,
                       user: CurrentUser = Depends(require_role("creator"))):
    video_id = req.video_id
    ext = ext_of(req.filename)
    if ext not in config.allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported extension .{ext}")

    # The pre-signed URL was issued to exactly one user; refuse to let anyone
    # else register the video it produced (spec 4.3).
    if not presign.claim_owner(video_id, user.id):
        raise HTTPException(
            status_code=403, detail="This upload token was not issued to you")

    original_path = os.path.join(config.original_dir, video_id, f"original.{ext}")
    if not os.path.exists(original_path):
        raise HTTPException(
            status_code=400,
            detail="Binary not found; finish the upload first",
        )

    await database.insert_video(video_id, req.title, req.description,
                                original_path, uploader_id=user.id)
    drm.generate_key(video_id)
    await push_task(redis, {"video_id": video_id, "original_path": original_path})
    logger.info("video %s queued for transcoding (uploader %s)", video_id, user.id)
    return {"video_id": video_id, "status": "pending"}


@app.get("/api/videos/mine")
async def my_videos(user: CurrentUser = Depends(require_role("creator"))):
    """Own uploads, failed ones included (spec 4.2).

    Declared BEFORE /api/videos/{video_id} so the literal segment is not
    swallowed by the path parameter.
    """
    rows = await database.list_videos_by_uploader(user.id)
    return {"videos": [_card(v) for v in rows]}


@app.get("/api/videos")
async def list_videos(limit: int = Query(50, ge=1, le=200),
                      offset: int = Query(0, ge=0)):
    rows = await database.list_videos_public(limit, offset)
    total = await database.count_videos_public()
    return {"videos": [_card(v) for v in rows], "total": total}


@app.get("/api/videos/{video_id}")
async def get_video(video_id: str,
                    viewer: CurrentUser | None = Depends(get_optional_user)):
    v = await database.get_video(video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    try:
        moderation_service.assert_visible(v, viewer)
    except moderation_service.NotFoundError:
        raise HTTPException(status_code=404, detail="Video not found")
    out = _card(v)
    out["error_msg"] = v["error_msg"]
    if v["status"] == "ready":
        out["stream_url"] = f"/media/{video_id}/master.m3u8"
        out["renditions"] = await database.get_renditions(video_id)
    return out


@app.post("/api/videos/{video_id}/retry")
async def retry_video(video_id: str,
                      user: CurrentUser = Depends(get_current_user)):
    v = await database.get_video(video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")

    is_owner = v.get("uploader_id") == user.id
    is_staff = (security.ROLE_LEVEL.get(user.role, 0)
                >= security.ROLE_LEVEL["moderator"])
    if not (is_owner or is_staff):
        raise HTTPException(status_code=403, detail="Not your video")

    if v["status"] != "failed":
        raise HTTPException(
            status_code=400, detail=f"Only failed videos can be retried (current: {v['status']})")
    if not v["original_path"] or not os.path.exists(v["original_path"]):
        raise HTTPException(status_code=400, detail="Original binary is missing")

    await database.set_video_status(video_id, "pending")
    await push_task(redis, {"video_id": video_id, "original_path": v["original_path"]})
    logger.info("video %s re-queued for transcoding by %s", video_id, user.id)
    return {"video_id": video_id, "status": "pending"}


@app.get("/api/stats")
async def stats(_: CurrentUser = Depends(require_role("moderator"))):
    queued = await redis.llen(config.task_queue)
    pattern = "worker:*"
    workers = 0
    async for _ in redis.scan_iter(match=pattern, count=100):
        workers += 1
    by_status = await database.count_by_status()
    return {"workers": workers, "queued_tasks": queued, "videos_by_status": by_status}
