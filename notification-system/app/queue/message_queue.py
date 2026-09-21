"""
Message Queue — Decouples notification sending from processing.

Design doc:
- "Use message queues to decouple system components."
- "Message queues serve as buffers when high volumes of notifications are to be sent out."
- "Add workers that pull notification events from message queues."

Uses asyncio.Queue for in-process demo. In production: Redis/RabbitMQ/Kafka.
"""
import asyncio
import logging
import time
from typing import Optional

from app.models import NotificationEvent

logger = logging.getLogger(__name__)


class MessageQueue:
    """
    In-memory async message queue for notification events.
    In production, replace with Redis Streams, RabbitMQ, or Kafka.
    """

    def __init__(self, maxsize: int = 10000):
        self._queue: asyncio.Queue[NotificationEvent] = asyncio.Queue(maxsize=maxsize)
        self._total_enqueued = 0
        self._total_dequeued = 0

    async def enqueue(self, event: NotificationEvent) -> bool:
        """Add a notification event to the queue."""
        try:
            self._queue.put_nowait(event)
            self._total_enqueued += 1
            return True
        except asyncio.QueueFull:
            logger.error("Message queue is full! Event dropped.")
            return False

    async def dequeue(self, timeout: float = None) -> Optional[NotificationEvent]:
        """Get the next event from the queue."""
        try:
            if timeout:
                event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            else:
                event = self._queue.get_nowait()
            self._total_dequeued += 1
            return event
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return None

    def requeue(self, event: NotificationEvent):
        """Put an event back at the front (for retry)."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.error("Cannot requeue: queue is full!")

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def stats(self) -> dict:
        return {
            "pending": self.pending_count,
            "total_enqueued": self._total_enqueued,
            "total_dequeued": self._total_dequeued,
        }
