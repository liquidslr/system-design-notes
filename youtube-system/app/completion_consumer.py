"""Consume worker events and apply them to the database.

Single-writer rule: only this module (running inside api-server) writes
worker results to SQLite. Workers report through the `transcode:events`
queue with three event types:

- processing: {type, video_id, duration_sec, width, height, renditions}
- ready:      {type, video_id, renditions: [{resolution, playlist_path}]}
- failed:     {type, video_id, error}
"""
import asyncio
import logging

from app import database
from app.queue import pop_event

logger = logging.getLogger(__name__)


async def handle_event(event: dict) -> None:
    etype = event.get("type")
    video_id = event.get("video_id", "?")

    if etype == "processing":
        await database.upsert_video_info(
            video_id, event.get("duration_sec"),
            event.get("width"), event.get("height"),
        )
        await database.set_video_status(video_id, "processing")
        await database.replace_renditions(video_id, event.get("renditions", []))
        logger.info("video %s: processing (%d renditions)",
                    video_id, len(event.get("renditions", [])))

    elif etype == "ready":
        for r in event.get("renditions", []):
            await database.set_rendition_done(
                video_id, r["resolution"], r["playlist_path"]
            )
        await database.set_video_status(video_id, "ready")
        logger.info("video %s: ready", video_id)

    elif etype == "failed":
        error = event.get("error", "unknown error")
        await database.set_video_status(video_id, "failed", error_msg=error)
        await database.set_renditions_failed(video_id)
        logger.warning("video %s: failed (%s)", video_id, error)

    else:
        logger.warning("unknown event type: %r", etype)


async def run_consumer(stop: asyncio.Event) -> None:
    from app.queue import create_client
    client = create_client()
    logger.info("Completion consumer started (queue: transcode:events)")
    try:
        while not stop.is_set():
            try:
                event = await pop_event(client, timeout=2)
                if event is not None:
                    await handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("consumer loop error; retrying in 2s")
                await asyncio.sleep(2)
    finally:
        await client.aclose()
        logger.info("Completion consumer stopped")
