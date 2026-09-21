import json
import logging
import time
from typing import Dict

from fastapi import WebSocket
import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

# Single global Pub/Sub channel for all message routing
GLOBAL_CHANNEL = "chat:messages"


class ConnectionManager:
    """Manages WebSocket connections and Redis Pub/Sub subscriptions."""

    def __init__(self):
        # user_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        self.redis: redis.Redis | None = None
        self.pubsub: redis.client.PubSub | None = None

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"User connected: {user_id}, total: {len(self.active_connections)}")

        # Register presence in Redis
        r = await self._get_redis()
        await r.set(f"user_server:{user_id}", settings.SERVICE_NAME)
        await r.hset(f"presence:{user_id}", mapping={
            "status": "online",
            "last_heartbeat": str(int(time.time())),
        })

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
        logger.info(f"User disconnected: {user_id}, total: {len(self.active_connections)}")

    async def cleanup(self, user_id: str):
        r = await self._get_redis()
        await r.delete(f"user_server:{user_id}")
        await r.hset(f"presence:{user_id}", mapping={"status": "offline"})

    async def send_personal(self, user_id: str, data: dict):
        ws = self.active_connections.get(user_id)
        if ws:
            await ws.send_json(data)

    async def listen_pubsub(self):
        """Listen for messages from Redis Pub/Sub global channel and forward to WebSocket clients."""
        while True:
            try:
                r = await self._get_redis()
                if self.pubsub is None:
                    self.pubsub = r.pubsub()
                    await self.pubsub.subscribe(GLOBAL_CHANNEL)
                    logger.info(f"Subscribed to global channel: {GLOBAL_CHANNEL}")

                async for message in self.pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        # Route to target users
                        target_ids = data.pop("target_user_ids", [])
                        for uid in target_ids:
                            await self.send_personal(uid, data)
                    except Exception:
                        logger.exception("Error processing Pub/Sub message")
            except Exception:
                logger.exception("Pub/Sub listener error, reconnecting in 2s...")
                self.pubsub = None
                import asyncio
                await asyncio.sleep(2)

    async def _get_redis(self) -> redis.Redis:
        if self.redis is None:
            self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self.redis


manager = ConnectionManager()
