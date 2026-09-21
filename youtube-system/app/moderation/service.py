"""Moderation business logic (spec 3.1).

Reaches the database only through app.database; raises domain exceptions
that router.py maps to HTTP codes. Reuses auth primitives (ROLE_LEVEL).
"""
from app import database
from app.auth.dependencies import CurrentUser
from app.auth.security import ROLE_LEVEL

_MODERATOR_LEVEL = ROLE_LEVEL["moderator"]


class NotFoundError(Exception):
    """404 - video not found or access denied (masquerades as 404)."""


class PermissionDenied(Exception):
    """403 - resubmit by non-owner."""


class ValidationError(Exception):
    """400 - illegal state transition."""


def _queue_card(v: dict) -> dict:
    """Format a video row for the moderation queue response."""
    return {
        "id": v["id"],
        "title": v["title"],
        "description": v["description"],
        "status": v["status"],
        "moderation_status": v.get("moderation_status", "pending_review"),
        "rejection_reason": v.get("rejection_reason"),
        "duration_sec": v["duration_sec"],
        "uploader": ({"id": v["uploader_id"], "username": v.get("uploader_username")}
                     if v.get("uploader_id") else None),
        "created_at": v["created_at"],
    }


async def list_queue(limit: int, offset: int) -> dict:
    rows = await database.list_moderation_queue(limit, offset)
    total = await database.count_moderation_queue()
    return {"videos": [_queue_card(r) for r in rows], "total": total}


async def approve(video_id: str, actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None:
        raise NotFoundError("video not found")
    if v["moderation_status"] != "pending_review":
        raise ValidationError("only pending_review videos can be approved")
    await database.set_moderation(video_id, "approved", None)


async def reject(video_id: str, reason: str, actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None:
        raise NotFoundError("video not found")
    if v["moderation_status"] != "pending_review":
        raise ValidationError("only pending_review videos can be rejected")
    await database.set_moderation(video_id, "rejected", reason)


async def resubmit(video_id: str, title: str, description: str,
                   actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None:
        raise NotFoundError("video not found")
    if v.get("uploader_id") != actor.id:
        raise PermissionDenied("not your video")
    if v["moderation_status"] != "rejected":
        raise ValidationError("only rejected videos can be resubmitted")
    await database.resubmit_video(video_id, title, description)


def assert_visible(video: dict, viewer: CurrentUser | None) -> None:
    """Gate for GET video detail: if not approved+ready, only owner/moderator+
    can view; others get 404 (existence not leaked)."""
    is_public = (video["status"] == "ready"
                 and video.get("moderation_status", "approved") == "approved")
    if is_public:
        return
    if viewer is None:
        raise NotFoundError("video not found")
    is_owner = video.get("uploader_id") == viewer.id
    is_staff = ROLE_LEVEL.get(viewer.role, 0) >= _MODERATOR_LEVEL
    if not (is_owner or is_staff):
        raise NotFoundError("video not found")
