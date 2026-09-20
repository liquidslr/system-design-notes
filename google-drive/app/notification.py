"""
Notification center: in-process pub/sub + DB-backed offline queue.
Uses asyncio.Event to wake long-poll waiters immediately.
"""
import asyncio
import json
import time

from .database import Database


class NotificationCenter:
    def __init__(self, db: Database):
        self._db = db
        self._event = asyncio.Event()

    async def publish(self, user_id: str, file_id: str, event: str, payload: dict):
        """Insert notification row and signal waiting pollers."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self._db.insert_notification(user_id, file_id, event, json.dumps(payload), now)
        self._event.set()  # wake all waiters

    async def poll(self, user_id: str, since_id: int, wait: float) -> list[dict]:
        """
        Long-poll: return new undelivered events or block up to `wait` seconds.
        Offline clients re-call with their last-seen since_id to pull backlog.
        """
        deadline = time.monotonic() + wait
        while True:
            events = await self._db.get_undelivered_notifications(user_id, since_id)
            if events:
                ids = [e["notif_id"] for e in events]
                await self._db.mark_notifications_delivered(ids)
                # parse payload JSON for convenience
                for e in events:
                    e["payload"] = json.loads(e.get("payload", "{}"))
                return events
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            self._event.clear()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=min(remaining, 0.5))
            except asyncio.TimeoutError:
                pass  # re-check DB
