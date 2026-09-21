"""
Fanout Service — Propagates posts to friends' news feeds.

Design doc:
- Fanout on Write: Push posts to friends' feeds at write time
- Hybrid: Pull model for users with many friends (celebrities)
- Fanout workers process events from message queue

Flow:
1. Fetch Friend IDs from graph DB/cache
2. Filter friends (muted, preferences)
3. Send friend list + post ID to message queue
4. Fanout workers update news feed cache
"""
import asyncio
import logging
import time
from typing import Optional

from app.config import FeedConfig
from app.cache import CacheLayer
from app.database import Database
from app.models import Post, FeedItem

logger = logging.getLogger(__name__)


class FanoutMessage:
    """Message in the fanout queue."""
    def __init__(self, post: Post, friend_ids: list[str]):
        self.post = post
        self.friend_ids = friend_ids
        self.created_at = time.time()


class FanoutService:
    """
    Fanout service that propagates posts to friends' feeds.
    Uses hybrid approach: push for normal users, pull for celebrities.
    """

    def __init__(self, config: FeedConfig, db: Database, cache: CacheLayer):
        self.config = config
        self.db = db
        self.cache = cache
        self._queue: asyncio.Queue[FanoutMessage] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._total_fanouts = 0
        self._total_skipped = 0

    async def start(self):
        """Start fanout workers."""
        self._running = True
        for i in range(self.config.fanout_worker_count):
            task = asyncio.create_task(self._worker_loop(i))
            self._workers.append(task)
        logger.info(f"Started {self.config.fanout_worker_count} fanout workers")

    async def stop(self):
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def fanout_post(self, post: Post):
        """
        Initiate fanout for a new post.
        Design doc: Hybrid approach — push for normal users, pull for celebrities.
        """
        # Get friend list (from cache or DB)
        friend_ids = await self._get_friends(post.user_id)

        if not friend_ids:
            logger.debug(f"No friends for user {post.user_id}, skipping fanout")
            return

        # Hybrid: Check if author has too many friends (celebrity)
        if len(friend_ids) > self.config.fanout_threshold:
            # Pull model: don't push to feeds, let friends pull on read
            logger.info(
                f"User {post.user_id} has {len(friend_ids)} friends (>{self.config.fanout_threshold}), "
                f"using pull model"
            )
            self._total_skipped += len(friend_ids)
            return

        # Push model: enqueue fanout message
        msg = FanoutMessage(post=post, friend_ids=friend_ids)
        await self._queue.put(msg)
        logger.debug(f"Queued fanout for post {post.post_id[:8]} to {len(friend_ids)} friends")

    async def _get_friends(self, user_id: str) -> list[str]:
        """Get friend list from cache or database."""
        # Try cache first (Layer 3: Social Graph Cache)
        cached = self.cache.get_friends(user_id)
        if cached is not None:
            return cached

        # Cache miss — fetch from DB
        friend_ids = await self.db.get_friends(user_id)
        self.cache.set_friends(user_id, friend_ids)
        return friend_ids

    async def _worker_loop(self, worker_id: int):
        """Worker loop: process fanout messages from queue."""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await self._process_fanout(msg, worker_id)
            except Exception as e:
                logger.error(f"Fanout worker {worker_id} error: {e}")

    async def _process_fanout(self, msg: FanoutMessage, worker_id: int):
        """Process a fanout message: update friends' feed caches."""
        post = msg.post
        feed_items_added = 0

        for friend_id in msg.friend_ids:
            self.cache.add_to_feed(
                user_id=friend_id,
                post_id=post.post_id,
                author_id=post.user_id,
                max_len=self.config.max_feed_length,
            )
            feed_items_added += 1

        # Also add to author's own feed
        self.cache.add_to_feed(
            user_id=post.user_id,
            post_id=post.post_id,
            author_id=post.user_id,
            max_len=self.config.max_feed_length,
        )

        self._total_fanouts += feed_items_added
        logger.debug(
            f"Worker {worker_id}: Fanout post {post.post_id[:8]} to {feed_items_added} feeds"
        )

    @property
    def stats(self) -> dict:
        return {
            "queue_pending": self._queue.qsize(),
            "total_fanouts": self._total_fanouts,
            "total_skipped_pull_model": self._total_skipped,
            "workers_active": len([w for w in self._workers if not w.done()]),
        }
