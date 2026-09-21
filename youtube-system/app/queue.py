"""Redis queue helpers (design doc: message queue decoupling upload and
transcoding pipelines)."""
import redis.asyncio as aioredis

from app.config import config


def create_client() -> aioredis.Redis:
    return aioredis.from_url(config.redis_url, decode_responses=True)


async def push_task(client: aioredis.Redis, task: dict) -> None:
    import json
    await client.lpush(config.task_queue, json.dumps(task))


async def push_event(client: aioredis.Redis, event: dict) -> None:
    import json
    await client.lpush(config.event_queue, json.dumps(event))


async def pop_event(client: aioredis.Redis, timeout: int = 2) -> dict | None:
    import json
    item = await client.blpop(config.event_queue, timeout=timeout)
    if item is None:
        return None
    return json.loads(item[1])
