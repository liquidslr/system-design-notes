import json
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Group, GroupMember, Message, Friendship
from app.schemas import (
    GroupCreate, GroupResponse, GroupMemberAdd, GroupMemberResponse, MessageResponse,
    GroupMemberStatusResponse, GroupInviteRequest, GroupInviteResponse,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    data: GroupCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = Group(
        id=uuid.uuid4(),
        name=data.name,
        description=data.description,
        creator_id=current_user.id,
    )
    db.add(group)
    await db.flush()

    # Add creator as admin member
    member = GroupMember(group_id=group.id, user_id=current_user.id, role="admin")
    db.add(member)
    await db.commit()
    await db.refresh(group)

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        creator_id=group.creator_id,
        max_members=group.max_members,
        created_at=group.created_at,
        member_count=1,
    )


@router.get("/my-groups", response_model=list[GroupResponse])
async def list_my_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Group)
        .join(GroupMember, Group.id == GroupMember.group_id)
        .where(GroupMember.user_id == current_user.id)
    )
    groups = result.scalars().all()

    responses = []
    for group in groups:
        count_result = await db.execute(
            select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group.id)
        )
        member_count = count_result.scalar()
        responses.append(
            GroupResponse(
                id=group.id,
                name=group.name,
                description=group.description,
                creator_id=group.creator_id,
                max_members=group.max_members,
                created_at=group.created_at,
                member_count=member_count,
            )
        )
    return responses


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gid = uuid.UUID(group_id)
    result = await db.execute(select(Group).where(Group.id == gid))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    count_result = await db.execute(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == gid)
    )
    member_count = count_result.scalar()

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        creator_id=group.creator_id,
        max_members=group.max_members,
        created_at=group.created_at,
        member_count=member_count,
    )


@router.post("/{group_id}/members")
async def add_member(
    group_id: str,
    data: GroupMemberAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gid = uuid.UUID(group_id)

    # Check if current user is admin
    result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == gid,
            GroupMember.user_id == current_user.id,
            GroupMember.role == "admin",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Only admins can add members")

    # Check member count
    count_result = await db.execute(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == gid)
    )
    if count_result.scalar() >= 100:
        raise HTTPException(status_code=400, detail="Group is full (max 100)")

    # Check if already member
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == data.user_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User is already a member")

    member = GroupMember(group_id=gid, user_id=data.user_id, role="member")
    db.add(member)
    await db.commit()
    return {"message": "Member added"}


@router.delete("/{group_id}/members/{user_id}")
async def remove_member(
    group_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gid = uuid.UUID(group_id)
    uid = uuid.UUID(user_id)

    # Check if current user is admin or removing self
    is_admin = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == gid,
            GroupMember.user_id == current_user.id,
            GroupMember.role == "admin",
        )
    )
    if not is_admin.scalar_one_or_none() and current_user.id != uid:
        raise HTTPException(status_code=403, detail="Only admins can remove other members")

    await db.execute(
        delete(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == uid)
    )
    await db.commit()
    return {"message": "Member removed"}


@router.get("/{group_id}/members", response_model=list[GroupMemberResponse])
async def list_members(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gid = uuid.UUID(group_id)
    result = await db.execute(
        select(User, GroupMember.role)
        .join(GroupMember, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == gid)
    )
    rows = result.all()
    return [
        GroupMemberResponse(user_id=user.id, username=user.username, nickname=user.nickname, role=role)
        for user, role in rows
    ]


@router.get("/{group_id}/members-with-status", response_model=list[GroupMemberStatusResponse])
async def list_members_with_status(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get group members with online status and friendship info."""
    gid = uuid.UUID(group_id)

    # Get all members
    result = await db.execute(
        select(User, GroupMember.role)
        .join(GroupMember, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == gid)
    )
    rows = result.all()

    # Get current user's friends
    friend_result = await db.execute(
        select(Friendship.friend_id).where(
            Friendship.user_id == current_user.id,
            Friendship.status == "accepted",
        )
    )
    friend_ids = set(str(fid) for fid in friend_result.scalars().all())

    # Get online statuses from Redis
    r = await get_redis()
    responses = []
    for user, role in rows:
        presence = await r.hgetall(f"presence:{user.id}")
        online_status = presence.get("status", "offline") if presence else "offline"
        responses.append(
            GroupMemberStatusResponse(
                user_id=user.id,
                username=user.username,
                nickname=user.nickname,
                avatar_url=user.avatar_url,
                role=role,
                online_status=online_status,
                is_friend=str(user.id) in friend_ids,
            )
        )

    await r.aclose()
    return responses


@router.post("/{group_id}/invite", response_model=GroupInviteResponse)
async def invite_friends_to_group(
    group_id: str,
    data: GroupInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite friends to join a group. Any member can invite."""
    gid = uuid.UUID(group_id)

    # Verify current user is a member
    result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == gid,
            GroupMember.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this group")

    # Verify each friend_id is actually a friend
    friend_result = await db.execute(
        select(Friendship.friend_id).where(
            Friendship.user_id == current_user.id,
            Friendship.status == "accepted",
        )
    )
    friend_ids = set(str(fid) for fid in friend_result.scalars().all())

    invited_ids = []
    for fid in data.friend_ids:
        fid_str = str(fid)
        if fid_str not in friend_ids:
            continue

        # Check if already a member
        member_result = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == gid,
                GroupMember.user_id == fid,
            )
        )
        if member_result.scalar_one_or_none():
            continue

        new_member = GroupMember(group_id=gid, user_id=fid, role="member")
        db.add(new_member)
        invited_ids.append(fid_str)

    await db.commit()

    # Publish invite notifications via Redis Pub/Sub
    if invited_ids:
        r = await get_redis()
        group_result = await db.execute(select(Group).where(Group.id == gid))
        group = group_result.scalar_one()

        for uid in invited_ids:
            payload = {
                "type": "group_invite",
                "target_user_ids": [uid],
                "group_id": str(gid),
                "group_name": group.name,
                "inviter_id": str(current_user.id),
            }
            await r.publish("chat:messages", json.dumps(payload))

        await r.aclose()

    return GroupInviteResponse(
        invited_ids=invited_ids,
        message=f"Invited {len(invited_ids)} friend(s) to group",
    )


@router.get("/{group_id}/messages", response_model=list[MessageResponse])
async def get_group_messages(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    before: str | None = None,
):
    gid = uuid.UUID(group_id)

    # Verify membership
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this group")

    r = await get_redis()
    inbox_key = f"inbox:{current_user.id}:{group_id}"

    if before:
        message_ids = await r.zrangebyscore(inbox_key, "-inf", float(before) - 1, start=0, num=limit, desc=True)
    else:
        message_ids = await r.zrevrange(inbox_key, 0, limit - 1)

    messages = []
    for mid in reversed(message_ids):
        msg_data = await r.get(f"message:{mid}")
        if msg_data:
            messages.append(MessageResponse(**json.loads(msg_data)))

    await r.aclose()

    # Fallback to PostgreSQL if Redis is empty
    if not messages:
        query = select(Message).where(Message.channel_id == group_id)
        if before:
            query = query.where(Message.id < int(before))
        query = query.order_by(Message.id.desc()).limit(limit)

        result = await db.execute(query)
        db_messages = result.scalars().all()

        for msg in reversed(db_messages):
            messages.append(MessageResponse(
                message_id=str(msg.id),
                sender_id=str(msg.sender_id),
                receiver_id=group_id,
                content=msg.content,
                type="text",
                timestamp=int(msg.created_at.timestamp()),
                channel_type=msg.channel_type,
            ))

        # Backfill Redis cache
        if db_messages:
            r = await get_redis()
            for msg in db_messages:
                msg_dict = {
                    "message_id": str(msg.id),
                    "sender_id": str(msg.sender_id),
                    "receiver_id": group_id,
                    "content": msg.content,
                    "type": "text",
                    "timestamp": int(msg.created_at.timestamp()),
                    "channel_type": msg.channel_type,
                }
                await r.set(f"message:{msg.id}", json.dumps(msg_dict))
                await r.zadd(inbox_key, {str(msg.id): msg.id})
            await r.aclose()

    return messages
