"""Video processing pipeline: preprocessor -> parallel task workers ->
master playlist assembly. Reports progress via Redis events."""
import asyncio
import json
import logging
import os
import shutil

from worker import task_worker
from worker.config import WorkerConfig
from worker.preprocessor import UnrecoverableError, probe, select_renditions

logger = logging.getLogger(__name__)
cfg = WorkerConfig()


async def _push_event(redis, event: dict) -> None:
    await redis.lpush(cfg.event_queue, json.dumps(event))


async def process_video(task: dict, redis, resource_manager) -> None:
    video_id = task["video_id"]
    src = task["original_path"]
    out_root = os.path.join(os.getenv("TRANSCODED_DIR", "data/transcoded"), video_id)

    try:
        # ---- Preprocessor: validate + select renditions ----
        info = probe(src)          # UnrecoverableError on bad input
        renditions = select_renditions(info["width"], info["height"])

        # Idempotent output dir (covers retries after partial failure)
        shutil.rmtree(out_root, ignore_errors=True)
        os.makedirs(out_root, exist_ok=True)

        # ---- DRM: prepare key_info.txt if an encryption key exists ----
        keys_dir = os.getenv("KEYS_DIR", "data/keys")
        key_file = os.path.join(keys_dir, f"{video_id}.key")
        key_info_path = None
        if os.path.exists(key_file):
            key_info_path = os.path.join(keys_dir, f"{video_id}_info.txt")
            with open(key_info_path, "w", encoding="utf-8") as kf:
                kf.write(f"/api/keys/{video_id}\n")
                kf.write(f"{key_file}\n")

        # ---- Stage 0 event: metadata + rendition set ----
        await _push_event(redis, {
            "type": "processing",
            "video_id": video_id,
            "duration_sec": info["duration_sec"],
            "width": info["width"],
            "height": info["height"],
            "renditions": [
                {"resolution": r["resolution"], "bitrate_kbps": r["bitrate_kbps"]}
                for r in renditions
            ],
        })

        # ---- Parallel encodes via resource manager; thumbnail alongside ----
        encode_jobs = [
            resource_manager.submit(
                f"{video_id}:{r['resolution']}",
                task_worker.encode_rendition(src, out_root, r,
                                              key_info_path=key_info_path),
            )
            for r in renditions
        ]
        thumbnail_task = asyncio.to_thread(
            task_worker.make_thumbnail, src, out_root)
        results = await asyncio.gather(thumbnail_task, *encode_jobs)
        thumbnail, done = results[0], results[1:]

        # ---- Assemble master playlist ----
        master = task_worker.build_master_playlist(list(done))
        with open(os.path.join(out_root, "master.m3u8"), "w", encoding="utf-8") as f:
            f.write(master)

        await _push_event(redis, {
            "type": "ready",
            "video_id": video_id,
            "renditions": done,
        })
        logger.info("video %s transcoded: %s (thumbnail=%s)", video_id,
                    ", ".join(d["resolution"] for d in done), bool(thumbnail))

    except UnrecoverableError as e:
        logger.error("video %s unrecoverable failure: %s", video_id, e)
        await _push_event(redis, {"type": "failed", "video_id": video_id,
                                  "error": str(e)})
    except Exception as e:  # noqa: BLE001 - unexpected pipeline crash
        logger.exception("video %s internal worker error", video_id)
        await _push_event(redis, {"type": "failed", "video_id": video_id,
                                  "error": f"internal worker error: {e}"})
