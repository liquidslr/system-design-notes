import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Friendship
from app.schemas import FriendResponse, PendingRequestResponse

router = APIRouter(prefix="/api/friends", tags=["friends"])


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.post("/request")
async def send_friend_request(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    friend_username = data.get("friend_username")
    if not friend_username:
        raise HTTPException(status_code=400, detail="friend_username is required")

    # Find target user
    result = await db.execute(select(User).where(User.username == friend_username))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot add yourself as friend")

    # Check existing friendship (both directions)
    result = await db.execute(
        select(Friendship).where(
            or_(
                (Friendship.user_id == current_user.id) & (Friendship.friend_id == target.id),
                (Friendship.user_id == target.id) & (Friendship.friend_id == current_user.id),
            )
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Friendship already exists")

    friendship = Friendship(user_id=current_user.id, friend_id=target.id, status="pending")
    db.add(friendship)
    await db.commit()
    return {"message": "Friend request sent"}


@router.get("/pending-requests", response_model=list[PendingRequestResponse])
async def list_pending_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all pending friend requests received by the current user."""
    result = await db.execute(
        select(Friendship).where(
            Friendship.friend_id == current_user.id,
            Friendship.status == "pending",
        )
    )
    requests = result.scalars().all()
    requester_ids = [r.user_id for r in requests]

    if not requester_ids:
        return []

    result = await db.execute(select(User).where(User.id.in_(requester_ids)))
    users = {u.id: u for u in result.scalars().all()}

    return [
        PendingRequestResponse(
            user_id=req.user_id,
            username=users[req.user_id].username,
            nickname=users[req.user_id].nickname,
            avatar_url=users[req.user_id].avatar_url,
            created_at=req.created_at,
        )
        for req in requests
        if req.user_id in users
    ]


@router.get("/sent-requests", response_model=list[PendingRequestResponse])
async def list_sent_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all friend requests sent by the current user."""
    result = await db.execute(
        select(Friendship).where(
            Friendship.user_id == current_user.id,
            Friendship.status == "pending",
        )
    )
    requests = result.scalars().all()
    target_ids = [r.friend_id for r in requests]

    if not target_ids:
        return []

    result = await db.execute(select(User).where(User.id.in_(target_ids)))
    users = {u.id: u for u in result.scalars().all()}

    return [
        PendingRequestResponse(
            user_id=req.friend_id,
            username=users[req.friend_id].username,
            nickname=users[req.friend_id].nickname,
            avatar_url=users[req.friend_id].avatar_url,
            created_at=req.created_at,
        )
        for req in requests
        if req.friend_id in users
    ]


@router.put("/{friend_id}/accept")
async def accept_friend_request(
    friend_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fid = uuid.UUID(friend_id)

    result = await db.execute(
        select(Friendship).where(
            Friendship.user_id == fid,
            Friendship.friend_id == current_user.id,
            Friendship.status == "pending",
        )
    )
    friendship = result.scalar_one_or_none()
    if not friendship:
        raise HTTPException(status_code=404, detail="Friend request not found")

    friendship.status = "accepted"

    # Add reverse direction for easy querying
    reverse = Friendship(user_id=current_user.id, friend_id=fid, status="accepted")
    db.add(reverse)
    await db.commit()
    return {"message": "Friend request accepted"}


@router.put("/{friend_id}/reject")
async def reject_friend_request(
    friend_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fid = uuid.UUID(friend_id)

    result = await db.execute(
        select(Friendship).where(
            Friendship.user_id == fid,
            Friendship.friend_id == current_user.id,
            Friendship.status == "pending",
        )
    )
    friendship = result.scalar_one_or_none()
    if not friendship:
        raise HTTPException(status_code=404, detail="Friend request not found")

    await db.delete(friendship)
    await db.commit()
    return {"message": "Friend request rejected"}


@router.delete("/{friend_id}/cancel")
async def cancel_friend_request(
    friend_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fid = uuid.UUID(friend_id)

    result = await db.execute(
        select(Friendship).where(
            Friendship.user_id == current_user.id,
            Friendship.friend_id == fid,
            Friendship.status == "pending",
        )
    )
    friendship = result.scalar_one_or_none()
    if not friendship:
        raise HTTPException(status_code=404, detail="Friend request not found")

    await db.delete(friendship)
    await db.commit()
    return {"message": "Friend request cancelled"}


@router.delete("/{friend_id}")
async def remove_friend(
    friend_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fid = uuid.UUID(friend_id)

    await db.execute(
        delete(Friendship).where(
            or_(
                (Friendship.user_id == current_user.id) & (Friendship.friend_id == fid),
                (Friendship.user_id == fid) & (Friendship.friend_id == current_user.id),
            )
        )
    )
    await db.commit()
    return {"message": "Friend removed"}


@router.get("", response_model=list[FriendResponse])
async def list_friends(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await get_redis()

    # Get all accepted friendships for current user
    result = await db.execute(
        select(Friendship).where(
            Friendship.user_id == current_user.id,
            Friendship.status == "accepted",
        )
    )
    friendships = result.scalars().all()
    friend_ids = [f.friend_id for f in friendships]

    if not friend_ids:
        await r.aclose()
        return []

    # Fetch friend user details
    result = await db.execute(select(User).where(User.id.in_(friend_ids)))
    friends = result.scalars().all()

    responses = []
    for friend in friends:
        # Check online status from Redis
        presence = await r.hgetall(f"presence:{friend.id}")
        online_status = presence.get("status", "offline") if presence else "offline"
        responses.append(
            FriendResponse(
                user_id=friend.id,
                username=friend.username,
                nickname=friend.nickname,
                avatar_url=friend.avatar_url,
                status="accepted",
                online_status=online_status,
            )
        )

    await r.aclose()
    return responses
