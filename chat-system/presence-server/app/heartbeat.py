import json
import time
import asyncio

import redis.asyncio as redis

from app.config import settings


class HeartbeatChecker:
    """Background task that checks for offline users."""

    def __init__(self):
        self.redis: redis.Redis | None = None
        self._running = False

    async def start(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._running = True
        asyncio.create_task(self._scan_loop())

    async def stop(self):
        self._running = False
        if self.redis:
            await self.redis.aclose()

    async def update_heartbeat(self, user_id: str):
        """Update heartbeat timestamp for a user."""
        await self.redis.hset(f"presence:{user_id}", mapping={
            "status": "online",
            "last_heartbeat": str(int(time.time())),
        })

    async def _scan_loop(self):
        """Periodically scan for users who haven't sent heartbeats."""
        while self._running:
            try:
                await asyncio.sleep(settings.SCAN_INTERVAL)
                await self._check_offline_users()
            except Exception:
                await asyncio.sleep(5)

    async def _check_offline_users(self):
        """Find users whose heartbeat is older than threshold and mark them offline."""
        now = int(time.time())
        cursor = 0
        offline_users = []

        while True:
            cursor, keys = await self.redis.scan(cursor, match="presence:*", count=100)
            for key in keys:
                data = await self.redis.hgetall(key)
                if data and data.get("status") == "online":
                    last_hb = int(data.get("last_heartbeat", 0))
                    if now - last_hb > settings.OFFLINE_THRESHOLD:
                        user_id = key.replace("presence:", "")
                        offline_users.append(user_id)

            if cursor == 0:
                break

        for user_id in offline_users:
            await self.redis.hset(f"presence:{user_id}", "status", "offline")
            # Broadcast offline status
            await self.redis.publish(
                f"channel:presence:{user_id}",
                json.dumps({"user_id": user_id, "status": "offline"}),
            )


heartbeat_checker = HeartbeatChecker()
