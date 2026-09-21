"""Worker entrypoint: heartbeat + task consumption + health endpoint."""
import asyncio
import json
import logging
import signal

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI

from worker.config import WorkerConfig
from worker.pipeline import process_video
from worker.resource_manager import ResourceManager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

cfg = WorkerConfig()
resource_manager = ResourceManager(cfg.concurrency)


async def heartbeat_loop(redis: aioredis.Redis, stop: asyncio.Event) -> None:
    """Expose liveness via worker:{instance_id} key with 60s TTL."""
    key = f"worker:{cfg.instance_id}"
    while not stop.is_set():
        try:
            await redis.set(key, "alive", ex=60)
        except Exception:  # noqa: BLE001 - redis may be restarting
            logger.warning("heartbeat failed; will retry")
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass


async def consume_loop(redis: aioredis.Redis, stop: asyncio.Event) -> None:
    logger.info("worker %s consuming tasks (concurrency=%d)",
                cfg.instance_id, cfg.concurrency)
    while not stop.is_set():
        try:
            item = await redis.blpop(cfg.task_queue, timeout=3)
            if item is None:
                continue
            task = json.loads(item[1])
            await process_video(task, redis, resource_manager)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep consuming after errors
            logger.exception("consume loop error; retrying")
            await asyncio.sleep(2)


# ---- Health endpoint (design doc: heartbeating mechanism) ----
health_app = FastAPI()


@health_app.get("/health")
async def health():
    return {"status": "ok", "active_encodes": resource_manager.active_count}


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    # Windows has no add_signal_handler; fall back to signal.signal
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    except NotImplementedError:
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())

    redis = aioredis.from_url(cfg.redis_url, decode_responses=True)
    hb_task = asyncio.create_task(heartbeat_loop(redis, stop))
    consumer_task = asyncio.create_task(consume_loop(redis, stop))

    uvi = uvicorn.Server(uvicorn.Config(
        health_app, host="0.0.0.0", port=cfg.health_port, log_level="warning"))
    uvi.install_signal_handlers = lambda: None  # we own signal handling
    uvi_task = asyncio.create_task(uvi.serve())

    logger.info("worker started: %s", cfg.instance_id)
    await stop.wait()

    # ---- Graceful shutdown ----
    logger.info("shutting down: finishing in-flight encodes...")
    hb_task.cancel()
    consumer_task.cancel()
    await asyncio.gather(hb_task, consumer_task, return_exceptions=True)
    await resource_manager.drain()
    uvi.should_exit = True
    await uvi_task
    try:
        await redis.delete(f"worker:{cfg.instance_id}")
    except Exception:  # noqa: BLE001
        pass
    await redis.aclose()
    logger.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
