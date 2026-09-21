"""
URL Frontier — The central URL queue system.

Implements the two-level queue architecture from the design:
  - Front queues (f1..fn): Priority-based queues (Prioritizer)
  - Back queues (b1..bn): Per-host FIFO queues (Politeness)

The Queue Router directs URLs from priority queues to domain-specific queues.
The Queue Selector picks the next URL respecting both priority and politeness.
"""
import asyncio
import logging
import time
from collections import defaultdict
from typing import Optional

from app.config import CrawlerConfig
from app.models import CrawlURL, Priority

logger = logging.getLogger(__name__)


class URLFrontier:
    """
    URL Frontier implementing politeness and priority.

    Uses a single priority-sorted queue with per-domain politeness tracking.
    When dequeuing, skips URLs from domains that were crawled too recently.
    """

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._lock = asyncio.Lock()

        # Main FIFO queue of URLs waiting to be crawled
        self._queue: list[CrawlURL] = []

        # Per-domain last crawl timestamp for politeness
        self._domain_last_crawl: dict[str, float] = defaultdict(float)

        # Stats
        self._total_enqueued = 0
        self._total_dequeued = 0

    async def enqueue(self, url: CrawlURL) -> bool:
        """Add a URL to the frontier."""
        async with self._lock:
            self._queue.append(url)
            self._total_enqueued += 1
            return True

    async def dequeue(self) -> Optional[CrawlURL]:
        """
        Get the next URL to crawl, respecting politeness.
        Scans the queue for the first URL whose domain is ready.
        """
        async with self._lock:
            now = time.time()
            delay = self.config.politeness_delay

            # Find first URL whose domain is ready (politeness check)
            for i, url in enumerate(self._queue):
                domain = url.domain
                elapsed = now - self._domain_last_crawl[domain]
                if elapsed >= delay:
                    # This domain is ready — take this URL
                    self._queue.pop(i)
                    self._domain_last_crawl[domain] = now
                    self._total_dequeued += 1
                    return url

            # No domain is ready yet
            return None

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def stats(self) -> dict:
        return {
            "pending": self.pending_count,
            "enqueued": self._total_enqueued,
            "dequeued": self._total_dequeued,
        }

    async def wait_for_ready(self, timeout: float = 5.0) -> bool:
        """Wait until a URL is available or timeout."""
        start = time.time()
        while time.time() - start < timeout:
            if self.pending_count > 0:
                # Check if any domain is ready
                now = time.time()
                delay = self.config.politeness_delay
                for url in self._queue:
                    if now - self._domain_last_crawl[url.domain] >= delay:
                        return True
            await asyncio.sleep(0.2)
        return False
