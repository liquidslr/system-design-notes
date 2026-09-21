"""Pre-signed upload URL service.

Simulates S3 pre-signed URLs (design doc: upload flow uses pre-signed URLs
so binary traffic bypasses the API server). Tokens live in memory with a
TTL and are single-use.
"""
import secrets
import time

from app.config import config


class PresignError(Exception):
    pass


def ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


# token -> {video_id, user_id, expires_at}. In-memory: single instance by design.
_tokens: dict[str, dict] = {}

# video_id -> user_id. Outlives the token, because POST /api/videos carries only
# a video_id and still has to prove who the pre-signed URL was issued to.
_owners: dict[str, str] = {}


def issue(filename: str, size: int, user_id: str) -> dict:
    ext = ext_of(filename)
    if ext not in config.allowed_exts:
        raise PresignError(
            f"Unsupported file type .{ext}; allowed: {', '.join(config.allowed_exts)}"
        )
    if size <= 0 or size > config.max_upload_bytes:
        raise PresignError(f"Size must be in (0, {config.max_upload_bytes}] bytes")

    video_id = secrets.token_hex(12)
    token = secrets.token_urlsafe(24)
    _tokens[token] = {
        "video_id": video_id,
        "user_id": user_id,
        "expires_at": time.time() + config.presign_ttl,
    }
    return {
        "token": token,
        "video_id": video_id,
        "upload_path": f"/api/upload/{token}",
        "expires_in": config.presign_ttl,
    }


def consume(token: str) -> dict | None:
    """Single-use consume; returns token info or None if invalid/expired."""
    info = _tokens.pop(token, None)
    if info is None or info["expires_at"] < time.time():
        return None
    # Carry the ownership over: the token dies here, but the video it produced
    # still has to be claimed by the same user in POST /api/videos.
    _owners[info["video_id"]] = info["user_id"]
    return info


def claim_owner(video_id: str, user_id: str) -> bool:
    """One-shot ownership check; consumes the mapping so it cannot be reused."""
    if _owners.get(video_id) != user_id:
        return False
    _owners.pop(video_id, None)
    return True
