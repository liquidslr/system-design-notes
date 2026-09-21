"""Resource manager (design doc: Resource Manager + virtual task queue).

Bounds worker concurrency with an asyncio.Semaphore; each video task runs
its encodes as subtasks tracked by this manager so shutdown can drain them.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


class ResourceManager:
    def __init__(self, concurrency: int):
        self._sem = asyncio.Semaphore(concurrency)
        self._running: dict[str, asyncio.Task] = {}

    def submit(self, task_id: str, coro) -> asyncio.Task:
        async def _guarded():
            async with self._sem:
                return await coro

        task = asyncio.create_task(_guarded(), name=f"encode:{task_id}")
        self._running[task_id] = task
        task.add_done_callback(lambda t, tid=task_id: self._running.pop(tid, None))
        return task

    @property
    def active_count(self) -> int:
        return len(self._running)

    async def drain(self, timeout: float = 30.0) -> None:
        """Wait for running encodes to finish during shutdown."""
        pending = [t for t in self._running.values() if not t.done()]
        if not pending:
            return
        logger.info("draining %d active encode(s)...", len(pending))
        done, still_pending = await asyncio.wait(pending, timeout=timeout)
        for t in still_pending:
            t.cancel()
        logger.info("drain complete")
