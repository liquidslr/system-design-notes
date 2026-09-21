import json

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Message
from app.schemas import MessageResponse

router = APIRouter(prefix="/api/channels", tags=["channels"])


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.get("/{user_id}/messages", response_model=list[MessageResponse])
async def get_channel_messages(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    before: str | None = None,
):
    r = await get_redis()

    # For 1-on-1 chat, the channel_id is the sorted pair of the two user IDs
    channel_id = "_".join(sorted([str(current_user.id), user_id]))
    inbox_key = f"inbox:{current_user.id}:{channel_id}"

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
        query = select(Message).where(Message.channel_id == channel_id)
        if before:
            query = query.where(Message.id < int(before))
        query = query.order_by(Message.id.desc()).limit(limit)

        result = await db.execute(query)
        db_messages = result.scalars().all()

        for msg in reversed(db_messages):
            messages.append(MessageResponse(
                message_id=str(msg.id),
                sender_id=str(msg.sender_id),
                receiver_id=user_id,
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
                    "receiver_id": user_id,
                    "content": msg.content,
                    "type": "text",
                    "timestamp": int(msg.created_at.timestamp()),
                    "channel_type": msg.channel_type,
                }
                await r.set(f"message:{msg.id}", json.dumps(msg_dict))
                await r.zadd(inbox_key, {str(msg.id): msg.id})
                # Also add to peer's inbox
                peer_inbox_key = f"inbox:{user_id}:{channel_id}"
                await r.zadd(peer_inbox_key, {str(msg.id): msg.id})
            await r.aclose()

    return messages
