"""
Background data aggregation worker.

Periodically processes raw query logs into frequency data and rebuilds the trie.
Simulates the data gathering pipeline from the system design:
  Analytics Logs → Aggregator → Worker → Trie Cache
"""
import asyncio
import logging
import time

from app import database as db
from app.config import config
from app.trie import Trie
from app.filter import SuggestionFilter

logger = logging.getLogger(__name__)


class Aggregator:
    """Background worker that aggregates query logs and rebuilds the trie."""

    def __init__(self, trie: Trie, suggestion_filter: SuggestionFilter):
        self.trie = trie
        self.filter = suggestion_filter
        self._last_aggregated_ts: float = 0
        self._aggregation_count: int = 0
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background aggregation loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"Aggregator started (interval: {config.aggregation_interval_seconds}s)"
        )

    async def stop(self) -> None:
        """Stop the background aggregation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Aggregator stopped")

    async def _run_loop(self) -> None:
        """Main aggregation loop."""
        while self._running:
            try:
                await self._aggregate()
            except Exception:
                logger.exception("Aggregation error")
            await asyncio.sleep(config.aggregation_interval_seconds)

    async def _aggregate(self) -> None:
        """
        One aggregation cycle:
        1. Read new query logs since last aggregation
        2. Count query frequencies
        3. Update the frequencies table
        4. Rebuild the trie from updated frequencies
        5. Remove filtered queries from the trie
        """
        start_time = time.time()

        # 1. Get new logs
        logs = await db.get_unaggregated_logs(self._last_aggregated_ts)
        if not logs:
            return

        # 2. Count frequencies
        query_counts: dict[str, int] = {}
        max_ts = 0
        for query, ts in logs:
            q = query.lower().strip()
            if q:
                query_counts[q] = query_counts.get(q, 0) + 1
            max_ts = max(max_ts, ts)

        # 3. Update frequencies table
        await db.aggregate_frequencies(query_counts)
        self._last_aggregated_ts = max_ts
        self._aggregation_count += len(logs)

        # 4. Rebuild trie from all frequencies
        all_freqs = await db.get_all_frequencies()

        # Remove filtered queries from frequencies before building trie
        filtered = self.filter._blocked
        clean_freqs = {q: f for q, f in all_freqs.items() if q not in filtered}

        self.trie.build_from_frequencies(clean_freqs)

        elapsed = time.time() - start_time
        logger.info(
            f"Aggregated {len(logs)} logs ({len(query_counts)} unique queries) "
            f"in {elapsed:.2f}s. Trie rebuilt with {len(clean_freqs)} queries."
        )

    async def rebuild_now(self) -> dict:
        """Manually trigger an aggregation cycle. Returns stats."""
        await self._aggregate()
        stats = self.trie.get_all_stats()
        stats["aggregation_count"] = self._aggregation_count
        return stats

    @property
    def aggregation_count(self) -> int:
        return self._aggregation_count
