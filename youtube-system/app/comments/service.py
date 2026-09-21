"""Comments + likes business logic (spec 5).

Reaches the database only through app.database; raises domain exceptions that
router.py maps to HTTP codes. Auth primitives are reused from app.auth, so role
constants live in exactly one place.
"""
import secrets

from app import database
from app.auth.security import ROLE_LEVEL
from app.comments import schemas

_MODERATOR_LEVEL = ROLE_LEVEL["moderator"]


class NotFoundError(Exception):
    """404 - video or comment does not exist."""


class ValidationError(Exception):
    """400 - empty/long content, cross-video reply, vote/reply on deleted."""


class PermissionDenied(Exception):
    """403 - neither the author nor moderator+."""


def _out(row: dict, reply_count: int = 0, my_vote: int = 0) -> dict:
    deleted = row["status"] == "deleted"
    author = ({"id": None, "username": "deleted"} if deleted
              else {"id": row["author_id"], "username": row.get("author_username")})
    return {
        "id": row["id"], "video_id": row["video_id"], "author": author,
        "content": schemas.DELETED_PLACEHOLDER if deleted else row["body"],
        "status": row["status"],
        "parent_id": row["parent_id"], "root_id": row["root_id"],
        "like_count": row["like_count"], "dislike_count": row["dislike_count"],
        "score": row["score"], "reply_count": reply_count,
        "my_vote": my_vote, "created_at": row["created_at"],
    }


async def create_comment(video_id: str, author_id: str, content: str,
                         reply_to: str | None = None) -> dict:
    body = (content or "").strip()
    if not body or len(body) > schemas.CONTENT_MAX:
        raise ValidationError("content must be 1-1000 characters")
    if await database.get_video(video_id) is None:
        raise NotFoundError("video not found")

    parent_id = root_id = None
    if reply_to:
        parent = await database.get_comment(reply_to)
        if parent is None:
            raise NotFoundError("comment not found")
        if parent["video_id"] != video_id:
            raise ValidationError("reply_to belongs to a different video")
        if parent["status"] != "active":
            raise ValidationError("cannot reply to a deleted comment")
        parent_id = parent["id"]
        root_id = parent["root_id"] or parent["id"]

    comment_id = secrets.token_hex(12)
    await database.insert_comment(
        comment_id, video_id, author_id, body, parent_id, root_id)
    row = await database.get_comment(comment_id)
    return _out(row, reply_count=0, my_vote=0)


async def list_comments(video_id: str, sort: str, limit: int, offset: int,
                        viewer) -> dict:
    if await database.get_video(video_id) is None:
        raise NotFoundError("video not found")
    order = sort if sort in ("top", "new") else "top"
    rows = await database.list_top_comments(video_id, order, limit, offset)
    total = await database.count_top_comments(video_id)
    ids = [r["id"] for r in rows]
    counts = await database.reply_counts(ids)
    votes = await database.viewer_votes(viewer.id, ids) if viewer else {}
    out = [_out(r, reply_count=counts.get(r["id"], 0),
                my_vote=votes.get(r["id"], 0)) for r in rows]
    return {"comments": out, "total": total,
            "has_more": offset + len(rows) < total}


async def list_replies(comment_id: str, limit: int, offset: int, viewer) -> dict:
    root = await database.get_comment(comment_id)
    if root is None or root["parent_id"] is not None:
        raise NotFoundError("top-level comment not found")
    rows = await database.list_replies(comment_id, limit, offset)
    total = await database.count_replies(comment_id)
    ids = [r["id"] for r in rows]
    votes = await database.viewer_votes(viewer.id, ids) if viewer else {}
    out = [_out(r, reply_count=0, my_vote=votes.get(r["id"], 0)) for r in rows]
    return {"comments": out, "total": total,
            "has_more": offset + len(rows) < total}


async def vote(comment_id: str, user_id: str, value: int) -> dict:
    if value not in (-1, 0, 1):
        raise ValidationError("value must be -1, 0 or 1")
    row = await database.get_comment(comment_id)
    if row is None:
        raise NotFoundError("comment not found")
    if row["status"] != "active":
        raise ValidationError("cannot vote on a deleted comment")
    counters = await database.apply_vote(user_id, comment_id, value)
    return {**counters, "my_vote": value}


async def delete_comment(comment_id: str, actor_id: str, actor_role: str) -> None:
    row = await database.get_comment(comment_id)
    if row is None:
        raise NotFoundError("comment not found")
    is_author = row["author_id"] == actor_id
    is_staff = ROLE_LEVEL.get(actor_role, 0) >= _MODERATOR_LEVEL
    if not (is_author or is_staff):
        raise PermissionDenied("not allowed to delete this comment")
    if row["status"] == "active":
        await database.soft_delete_comment(comment_id)
