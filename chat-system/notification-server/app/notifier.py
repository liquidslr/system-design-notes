import json
import asyncio

import redis.asyncio as redis

from app.config import settings


class NotificationService:
    """Subscribes to Redis offline notification channel and logs/processes notifications."""

    def __init__(self):
        self.redis: redis.Redis | None = None
        self.pubsub: redis.client.PubSub | None = None
        self._running = False
        self.notifications: list[dict] = []  # In-memory log for demo

    async def start(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe("notification:offline")
        self._running = True
        asyncio.create_task(self._listen())

    async def stop(self):
        self._running = False
        if self.pubsub:
            await self.pubsub.unsubscribe("notification:offline")
            await self.pubsub.aclose()
        if self.redis:
            await self.redis.aclose()

    async def _listen(self):
        """Listen for offline notifications."""
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    self.notifications.append(data)
                    # In production: send push notification via APNs/FCM
                    print(
                        f"[NOTIFICATION] User {data['user_id']} has offline message "
                        f"from {data['message']['sender_id']}"
                    )
        except Exception:
            pass


notification_service = NotificationService()
