import json
import logging
import time

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text

from app.config import settings
from app.snowflake import generator
from app.connection_manager import GLOBAL_CHANNEL

logger = logging.getLogger(__name__)

# Database setup for chat server
engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


async def handle_send_message(sender_id: str, receiver_id: str, content: str, channel_type: str):
    """Process an outgoing message."""
    r = await get_redis()
    msg_id = str(generator.generate())
    timestamp = int(time.time())

    # Compute channel_id
    if channel_type == "one_to_one":
        channel_id = "_".join(sorted([sender_id, receiver_id]))
    else:
        channel_id = receiver_id  # group_id

    message = {
        "message_id": msg_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "content": content,
        "type": "text",
        "timestamp": timestamp,
        "channel_type": channel_type,
    }

    # Store message in Redis KV store
    await r.set(f"message:{msg_id}", json.dumps(message))

    # Persist to PostgreSQL (best-effort)
    try:
        async with async_session() as db:
            await db.execute(
                text(
                    "INSERT INTO messages (id, sender_id, channel_type, channel_id, content) "
                    "VALUES (:id, :sender_id, :channel_type, :channel_id, :content)"
                ),
                {
                    "id": int(msg_id),
                    "sender_id": sender_id,
                    "channel_type": channel_type,
                    "channel_id": channel_id,
                    "content": content,
                },
            )
            await db.commit()
    except Exception:
        logger.exception(f"Failed to persist message {msg_id} to PostgreSQL")

    if channel_type == "one_to_one":
        await _handle_one_to_one(r, sender_id, receiver_id, message)
    elif channel_type == "group":
        await _handle_group_message(r, sender_id, receiver_id, message)

    await r.aclose()
    return message


async def _handle_one_to_one(r: redis.Redis, sender_id: str, receiver_id: str, message: dict):
    """Handle one-to-one message delivery."""
    channel_id = "_".join(sorted([sender_id, receiver_id]))

    # Add to sender's inbox
    await r.zadd(
        f"inbox:{sender_id}:{channel_id}",
        {message["message_id"]: int(message["message_id"])},
    )

    # Add to receiver's inbox
    await r.zadd(
        f"inbox:{receiver_id}:{channel_id}",
        {message["message_id"]: int(message["message_id"])},
    )

    # Publish to global channel with receiver as target
    payload = {
        "type": "new_message",
        "message": message,
        "target_user_ids": [receiver_id],
    }
    await r.publish(GLOBAL_CHANNEL, json.dumps(payload))
    logger.info(f"Message {message['message_id']} delivered to global channel for user {receiver_id}")


async def _handle_group_message(r: redis.Redis, sender_id: str, group_id: str, message: dict):
    """Handle group message with fanout-on-write."""
    # Get all group members from database
    async with async_session() as db:
        result = await db.execute(
            text("SELECT user_id FROM group_members WHERE group_id = :gid"),
            {"gid": group_id},
        )
        member_ids = [str(row[0]) for row in result.fetchall()]

    # Fanout: add to each member's inbox
    target_user_ids = []
    for member_id in member_ids:
        await r.zadd(
            f"inbox:{member_id}:{group_id}",
            {message["message_id"]: int(message["message_id"])},
        )
        if member_id != sender_id:
            # Check if member is online
            presence = await r.hgetall(f"presence:{member_id}")
            if presence and presence.get("status") == "online":
                target_user_ids.append(member_id)
            else:
                await r.publish("notification:offline", json.dumps({
                    "user_id": member_id,
                    "message": message,
                }))

    # Broadcast to online members via global Pub/Sub channel
    if target_user_ids:
        payload = {
            "type": "new_message",
            "message": message,
            "target_user_ids": target_user_ids,
        }
        await r.publish(GLOBAL_CHANNEL, json.dumps(payload))
        logger.info(f"Group message {message['message_id']} delivered for group {group_id} to {len(target_user_ids)} users")


async def handle_sync(user_id: str, channel_id: str, last_message_id: str):
    """Sync messages for a user since last_message_id."""
    r = await get_redis()
    inbox_key = f"inbox:{user_id}:{channel_id}"

    # Get all message IDs greater than last_message_id
    min_score = str(float(last_message_id) + 1) if last_message_id != "0" else "-inf"
    message_ids = await r.zrangebyscore(inbox_key, min_score, "+inf")

    messages = []
    for mid in message_ids:
        msg_data = await r.get(f"message:{mid}")
        if msg_data:
            messages.append(json.loads(msg_data))

    await r.aclose()
    return messages


async def recover_messages_from_db():
    """Recover recent messages from PostgreSQL to Redis on startup."""
    r = await get_redis()
    try:
        async with async_session() as db:
            # Get distinct channels
            result = await db.execute(
                text("SELECT DISTINCT channel_id FROM messages")
            )
            channels = [row[0] for row in result.fetchall()]

            total = 0
            for channel_id in channels:
                # Get recent 100 messages per channel
                result = await db.execute(
                    text(
                        "SELECT id, sender_id, channel_type, channel_id, content, created_at "
                        "FROM messages WHERE channel_id = :cid "
                        "ORDER BY id DESC LIMIT 100"
                    ),
                    {"cid": channel_id},
                )
                rows = result.fetchall()

                for row in rows:
                    msg_id = str(row[0])
                    message = {
                        "message_id": msg_id,
                        "sender_id": str(row[1]),
                        "receiver_id": "",
                        "content": row[4],
                        "type": "text",
                        "timestamp": int(row[5].timestamp()) if row[5] else 0,
                        "channel_type": row[2],
                    }

                    # Backfill Redis KV
                    await r.set(f"message:{msg_id}", json.dumps(message))

                    if row[2] == "one_to_one":
                        parts = row[3].split("_")
                        if len(parts) == 2:
                            for uid in parts:
                                await r.zadd(
                                    f"inbox:{uid}:{row[3]}",
                                    {msg_id: int(msg_id)},
                                )
                    else:
                        members_result = await db.execute(
                            text("SELECT user_id FROM group_members WHERE group_id = :gid"),
                            {"gid": row[3]},
                        )
                        for member_row in members_result.fetchall():
                            await r.zadd(
                                f"inbox:{str(member_row[0])}:{row[3]}",
                                {msg_id: int(msg_id)},
                            )

                total += len(rows)

            logger.info(f"Recovered {total} messages from PostgreSQL to Redis across {len(channels)} channels")
    except Exception:
        logger.exception("Failed to recover messages from PostgreSQL")
    finally:
        await r.aclose()
