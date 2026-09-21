"""DRM: HLS AES-128 key generation and authenticated key delivery.

Design: docs/superpowers/specs/2026-09-18-youtube-drm-watermark-design.md §5.
"""
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response

from app import database
from app.auth.dependencies import CurrentUser, get_current_user
from app.moderation.service import NotFoundError, assert_visible

router = APIRouter()

KEYS_DIR = os.getenv("KEYS_DIR", "data/keys")


def generate_key(video_id: str) -> None:
    """Generate a 16-byte AES-128 key for a video. Idempotent."""
    path = os.path.join(KEYS_DIR, f"{video_id}.key")
    if os.path.exists(path):
        return
    os.makedirs(KEYS_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(secrets.token_bytes(16))


@router.get("/api/keys/{video_id}")
async def get_key(video_id: str,
                  viewer: CurrentUser = Depends(get_current_user)):
    """Serve the AES-128 content key for an encrypted video (authenticated)."""
    v = await database.get_video(video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    try:
        assert_visible(v, viewer)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Video not found")
    key_path = os.path.join(KEYS_DIR, f"{video_id}.key")
    if not os.path.exists(key_path):
        raise HTTPException(status_code=404, detail="Video is not encrypted")
    with open(key_path, "rb") as f:
        key_bytes = f.read()
    return Response(
        content=key_bytes,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
