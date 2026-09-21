"""
Workers — Pull events from queue and send via third-party providers.

Design doc:
- "Workers process events and interact with third-party services."
- Retry mechanism: "Retry sending notifications if third-party services fail."
- Event tracking: "Collect metrics like open rate, click rate, and engagement."
"""
import asyncio
import logging
import time
import uuid

from app.config import NotificationConfig
from app.database import Database
from app.models import NotificationEvent, NotificationLog, NotificationStatus
from app.providers.providers import ProviderRegistry
from app.queue.message_queue import MessageQueue

logger = logging.getLogger(__name__)


class WorkerPool:
    """
    Pool of async workers that consume notification events from the queue
    and send them via the appropriate third-party provider.
    """

    def __init__(
        self,
        config: NotificationConfig,
        db: Database,
        queue: MessageQueue,
        providers: ProviderRegistry,
    ):
        self.config = config
        self.db = db
        self.queue = queue
        self.providers = providers
        self._workers: list[asyncio.Task] = []
        self._running = False

        # Stats
        self._total_sent = 0
        self._total_failed = 0
        self._total_retried = 0

    async def start(self):
        """Start all worker tasks."""
        self._running = True
        for i in range(self.config.num_workers):
            task = asyncio.create_task(self._worker_loop(i))
            self._workers.append(task)
        logger.info(f"Started {self.config.num_workers} workers")

    async def stop(self):
        """Stop all workers."""
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("All workers stopped")

    async def _worker_loop(self, worker_id: int):
        """Main worker loop: dequeue events and send."""
        while self._running:
            event = await self.queue.dequeue(timeout=self.config.queue_poll_interval)
            if event is None:
                continue

            try:
                await self._process_event(event, worker_id)
            except Exception as e:
                logger.error(f"Worker {worker_id} error processing event {event.event_id}: {e}")
                self._total_failed += 1

    async def _process_event(self, event: NotificationEvent, worker_id: int):
        """Process a single notification event with retry logic."""
        provider = self.providers.get(event.channel.value)
        if not provider:
            logger.error(f"No provider for channel: {event.channel.value}")
            await self._mark_failed(event, f"No provider for {event.channel.value}")
            return

        # Attempt to send with retries
        for attempt in range(self.config.max_retries + 1):
            try:
                success = await provider.send(
                    recipient=event.recipient,
                    title=event.title,
                    body=event.body,
                    metadata=event.metadata,
                )

                if success:
                    await self._mark_sent(event)
                    logger.debug(
                        f"Worker {worker_id}: Sent {event.channel.value} to {event.recipient[:20]}... "
                        f"(event={event.event_id[:8]})"
                    )
                    return
                else:
                    # Provider returned failure
                    if attempt < self.config.max_retries:
                        await self._retry(event, attempt + 1)
                    else:
                        await self._mark_failed(event, "Provider returned failure after all retries")

            except Exception as e:
                if attempt < self.config.max_retries:
                    await self._retry(event, attempt + 1)
                else:
                    await self._mark_failed(event, str(e))

    async def _retry(self, event: NotificationEvent, attempt: int):
        """Schedule a retry with exponential backoff."""
        self._total_retried += 1
        delay = self.config.retry_delay_seconds * (self.config.retry_backoff_multiplier ** (attempt - 1))
        event.retry_count = attempt
        event.status = NotificationStatus.RETRYING

        logger.info(
            f"Retry {attempt}/{self.config.max_retries} for event {event.event_id[:8]} "
            f"(channel={event.channel.value}, delay={delay:.1f}s)"
        )

        # Wait with exponential backoff
        await asyncio.sleep(delay)

        # Re-enqueue for retry
        self.queue.requeue(event)

    async def _mark_sent(self, event: NotificationEvent):
        """Mark event as successfully sent."""
        self._total_sent += 1
        await self.db.update_log_status(
            event.event_id,
            NotificationStatus.SENT.value,
            sent_at=time.time(),
        )

    async def _mark_failed(self, event: NotificationEvent, error: str):
        """Mark event as failed."""
        self._total_failed += 1
        event.status = NotificationStatus.FAILED
        logger.warning(f"Event {event.event_id[:8]} failed: {error}")
        await self.db.update_log_status(
            event.event_id,
            NotificationStatus.FAILED.value,
            error_message=error,
        )

    @property
    def stats(self) -> dict:
        return {
            "workers_active": len([w for w in self._workers if not w.done()]),
            "total_sent": self._total_sent,
            "total_failed": self._total_failed,
            "total_retried": self._total_retried,
        }
