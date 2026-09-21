# YouTube 视频流系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现YouTube 风格的视频上传→ffmpeg 转码→HLS 流媒体播放系统。

**Architecture:** 5 容器微服务（frontend / api-server / transcoder-worker / cdn / redis）。api-server 持有 SQLite 单写者，Worker 通过 Redis 队列（transcode:tasks / transcode:events）解耦通信，ffmpeg 产出标准 HLS 多码率产物，nginx 模拟 CDN 分发。

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, redis-py(async), ffmpeg, Vue 3 + Vite + HLS.js, Docker Compose

**规格文档:** `docs/superpowers/specs/2026-09-17-youtube-video-streaming-design.md`

**实施细化说明（相对规格的两处实现细化）:**
1. Worker 不直接写 SQLite（避免双写者锁冲突）：Worker 推送 `transcode:events` 事件（processing/ready/failed），由 api-server 的完成消费协程更新 DB。renditions 行由消费端在 processing 事件时按 Worker 上报的档位集合创建。
2. `/api/stats` 的 Worker 数通过 Worker 心跳键（`worker:{instance_id}`，TTL 60s）+ SCAN 统计。
3. 仓库无 pytest 基础设施（沿用项目模式），每个任务以"验证步骤"（可执行命令+期望输出）代替单元测试。

---

## 文件结构总览

```
youtube-system/
├── app/                          # api-server
│   ├── __init__.py               # 空
│   ├── config.py                 # 配置（存储路径/Redis/上传规则）
│   ├── models.py                 # Pydantic 请求/响应模型
│   ├── database.py               # SQLite 异步层（videos, renditions）
│   ├── presign.py                # 预签名 token（单次有效/300s 过期）
│   ├── queue.py                  # Redis 队列助手
│   ├── completion_consumer.py    # 后台事件消费 → 更新 DB
│   └── server.py                 # FastAPI 全部端点
├── worker/                       # transcoder-worker
│   ├── __init__.py               # 空
│   ├── config.py                 # Worker 配置
│   ├── preprocessor.py           # ffprobe 探测 + 档位规划
│   ├── task_worker.py            # ffmpeg 执行 + 重试 + master.m3u8 生成
│   ├── resource_manager.py       # 并发闸门 + 运行中任务追踪
│   ├── pipeline.py               # DAG 调度（Stage 0/1/2 + 完成事件）
│   └── main.py                   # 入口：消费循环 + 心跳 + health + 优雅停机
├── cdn/nginx.conf                # CDN nginx（HLS MIME + CORS）
├── frontend/
│   ├── package.json / vite.config.js / index.html
│   ├── Dockerfile / nginx.conf / .dockerignore
│   └── src/
│       ├── main.js / router.js / api.js / App.vue
│       └── views/HomeView.vue / UploadView.vue / WatchView.vue
├── Dockerfile                    # api-server 镜像
├── worker.Dockerfile             # worker 镜像（含 ffmpeg）
├── docker-compose.yml
├── .dockerignore
├── requirements.txt
└── README.md
```

---

### Task 1: api-server 基础（config / models / database）

**Files:**
- Create: `youtube-system/requirements.txt`
- Create: `youtube-system/app/__init__.py`（空文件）
- Create: `youtube-system/app/config.py`
- Create: `youtube-system/app/models.py`
- Create: `youtube-system/app/database.py`

- [ ] **Step 1: 创建 requirements.txt**

```text
fastapi==0.115.0
uvicorn[standard]==0.30.6
aiosqlite==0.20.0
pydantic==2.9.2
redis==5.0.8
```

- [ ] **Step 2: 创建 app/config.py**

```python
"""Configuration for the YouTube video streaming system (api-server)."""
import os
from dataclasses import dataclass


@dataclass
class Config:
    # Storage (volume-mounted at /app/data in Docker)
    db_path: str = os.getenv("DB_PATH", "data/youtube.db")
    original_dir: str = os.getenv("ORIGINAL_DIR", "data/original")
    transcoded_dir: str = os.getenv("TRANSCODED_DIR", "data/transcoded")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Redis queues (design doc: message queue decoupling)
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    task_queue: str = "transcode:tasks"
    event_queue: str = "transcode:events"

    # Upload rules (design doc assumptions: max 1GB per video)
    presign_ttl: int = 300
    max_upload_bytes: int = 1 << 30  # 1GB
    allowed_exts: tuple = ("mp4", "mov", "avi", "mkv", "webm")


config = Config()
```

- [ ] **Step 3: 创建 app/models.py**

```python
"""Pydantic models for api-server request/response validation."""
from pydantic import BaseModel, Field


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    size: int = Field(..., gt=0)
    content_type: str = "video/mp4"


class UploadUrlResponse(BaseModel):
    token: str
    video_id: str
    upload_path: str
    expires_in: int


class VideoCreateRequest(BaseModel):
    video_id: str = Field(..., min_length=8, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    filename: str = Field(..., min_length=1, max_length=255)  # 用于推导扩展名
```

- [ ] **Step 4: 创建 app/database.py**

```python
"""Async SQLite storage for video metadata.

Single-writer design: only api-server touches this database. Workers
communicate state changes through Redis events consumed by
completion_consumer.py.
"""
import logging
import os
import time
import uuid

import aiosqlite

from app.config import config

logger = logging.getLogger(__name__)


async def init_db() -> None:
    os.makedirs(os.path.dirname(config.db_path), exist_ok=True)
    async with aiosqlite.connect(config.db_path) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                original_path TEXT,
                duration_sec REAL,
                width INTEGER,
                height INTEGER,
                error_msg TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS renditions (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL REFERENCES videos(id),
                resolution TEXT NOT NULL,
                playlist_path TEXT,
                bitrate_kbps INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(video_id, resolution)
            );
            CREATE INDEX IF NOT EXISTS idx_renditions_video ON renditions(video_id);
        """)
        await db.commit()
    logger.info("Database initialized")


async def insert_video(video_id: str, title: str, description: str,
                       original_path: str) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO videos (id, title, description, status, original_path,
                                   created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 original_path=excluded.original_path, status='pending',
                 error_msg=NULL, updated_at=excluded.updated_at""",
            (video_id, title, description, original_path, now, now),
        )
        await db.commit()


async def get_video(video_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_videos() -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM videos ORDER BY created_at DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def set_video_status(video_id: str, status: str,
                           error_msg: str | None = None) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE videos SET status = ?, error_msg = ?, updated_at = ? WHERE id = ?",
            (status, error_msg, time.time(), video_id),
        )
        await db.commit()


async def upsert_video_info(video_id: str, duration_sec: float | None,
                            width: int | None, height: int | None) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """UPDATE videos
               SET duration_sec = ?, width = ?, height = ?, updated_at = ?
               WHERE id = ?""",
            (duration_sec, width, height, time.time(), video_id),
        )
        await db.commit()


async def replace_renditions(video_id: str, renditions: list[dict]) -> None:
    """Replace rendition rows with the set announced by the worker."""
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute("DELETE FROM renditions WHERE video_id = ?", (video_id,))
        for r in renditions:
            await db.execute(
                """INSERT INTO renditions (id, video_id, resolution, bitrate_kbps, status)
                   VALUES (?, ?, ?, ?, 'processing')""",
                (uuid.uuid4().hex, video_id, r["resolution"], r["bitrate_kbps"]),
            )
        await db.commit()


async def set_rendition_done(video_id: str, resolution: str,
                             playlist_path: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """UPDATE renditions SET status = 'done', playlist_path = ?
               WHERE video_id = ? AND resolution = ?""",
            (playlist_path, video_id, resolution),
        )
        await db.commit()


async def set_renditions_failed(video_id: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE renditions SET status = 'failed' WHERE video_id = ?", (video_id,)
        )
        await db.commit()


async def get_renditions(video_id: str) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT resolution, playlist_path, bitrate_kbps, status
               FROM renditions WHERE video_id = ?""",
            (video_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_by_status() -> dict[str, int]:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute("SELECT status, COUNT(*) FROM videos GROUP BY status")
        return {row[0]: row[1] for row in await cursor.fetchall()}
```

- [ ] **Step 5: 验证（本地 venv 导入检查）**

Run: `cd D:\StudyProjects\system-design-notes; .\venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'youtube-system'); from app import config, models, database; print('ok')"`
Expected: `ok`（若 aiosqlite/redis 未装：`.\venv\Scripts\pip.exe install -r youtube-system\requirements.txt`）

- [ ] **Step 6: 提交（可选，随最终任务统一提交亦可）**

```bash
git add youtube-system/
git commit -m "feat(youtube): api-server base config/models/database"
```

---

### Task 2: 预签名与 Redis 队列助手

**Files:**
- Create: `youtube-system/app/presign.py`
- Create: `youtube-system/app/queue.py`

- [ ] **Step 1: 创建 app/presign.py**

```python
"""Pre-signed upload tokens (design doc: Safety Optimizations).

Tokens are single-use, expire after config.presign_ttl seconds, and are
bound to a server-generated video_id.
"""
import secrets
import time

from app.config import config

_tokens: dict[str, dict] = {}


class PresignError(Exception):
    """Invalid upload request or token."""


def ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def issue(filename: str, size: int) -> dict:
    ext = ext_of(filename)
    if ext not in config.allowed_exts:
        raise PresignError(f"Unsupported file extension: .{ext}")
    if size > config.max_upload_bytes:
        raise PresignError("File exceeds 1GB limit")

    video_id = secrets.token_hex(12)
    token = secrets.token_urlsafe(24)
    _tokens[token] = {
        "video_id": video_id,
        "ext": ext,
        "expires_at": time.time() + config.presign_ttl,
    }
    return {
        "token": token,
        "video_id": video_id,
        "upload_path": f"/api/upload/{token}",
        "expires_in": config.presign_ttl,
    }


def consume(token: str) -> dict:
    """Pop and validate a token (single use). Raises PresignError."""
    entry = _tokens.pop(token, None)
    if entry is None:
        raise PresignError("Invalid or already-used upload token")
    if time.time() > entry["expires_at"]:
        raise PresignError("Upload token expired")
    return entry
```

- [ ] **Step 2: 创建 app/queue.py**

```python
"""Redis queue helpers (design doc: completion queue / message queue)."""
import json
import logging

import redis.asyncio as aioredis

from app.config import config

logger = logging.getLogger(__name__)


def create_client() -> aioredis.Redis:
    return aioredis.from_url(config.redis_url, decode_responses=True)


async def push_task(r: aioredis.Redis, task: dict) -> None:
    await r.lpush(config.task_queue, json.dumps(task))


async def push_event(r: aioredis.Redis, event: dict) -> None:
    await r.lpush(config.event_queue, json.dumps(event))


async def pop_event(r: aioredis.Redis, timeout: int = 5) -> dict | None:
    item = await r.blpop(config.event_queue, timeout=timeout)
    if item is None:
        return None
    return json.loads(item[1])
```

- [ ] **Step 3: 验证**

Run: `.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'youtube-system'); from app import presign, queue; t=presign.issue('a.mp4', 100); print(t['video_id'] and 'ok')"`
Expected: `ok`

---

### Task 3: 完成事件消费协程

**Files:**
- Create: `youtube-system/app/completion_consumer.py`

- [ ] **Step 1: 创建 app/completion_consumer.py**

```python
"""Background coroutine: consume transcoder events and update metadata DB.

Worker events (JSON on transcode:events):
  {"video_id", "type": "processing", duration_sec, width, height,
   "renditions": [{"resolution", "bitrate_kbps"}]}
  {"video_id", "type": "ready", "renditions": [{"resolution", "playlist_path", "bitrate_kbps"}]}
  {"video_id", "type": "failed", "error": "..."}
"""
import asyncio
import logging

from app import database as db
from app.queue import create_client, pop_event

logger = logging.getLogger(__name__)


async def handle_event(event: dict) -> None:
    video_id, etype = event["video_id"], event["type"]

    if etype == "processing":
        await db.upsert_video_info(video_id, event.get("duration_sec"),
                                   event.get("width"), event.get("height"))
        await db.set_video_status(video_id, "processing")
        await db.replace_renditions(video_id, event["renditions"])

    elif etype == "ready":
        for r in event["renditions"]:
            await db.set_rendition_done(video_id, r["resolution"], r["playlist_path"])
        await db.set_video_status(video_id, "ready")
        logger.info("Video %s is ready", video_id)

    elif etype == "failed":
        await db.set_video_status(video_id, "failed",
                                  event.get("error", "transcoding failed"))
        await db.set_renditions_failed(video_id)
        logger.warning("Video %s failed: %s", video_id, event.get("error"))

    else:
        logger.warning("Unknown event type %r for video %s", etype, video_id)


async def run_consumer(stop: asyncio.Event) -> None:
    r = create_client()
    try:
        while not stop.is_set():
            try:
                event = await pop_event(r, timeout=2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Redis error; retrying in 2s")
                await asyncio.sleep(2)
                continue
            if event is None:
                continue
            try:
                await handle_event(event)
            except Exception:
                logger.exception("Failed to handle event for %s", event.get("video_id"))
    finally:
        await r.aclose()
```

- [ ] **Step 2: 验证（导入检查）**

Run: `.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'youtube-system'); from app import completion_consumer; print('ok')"`
Expected: `ok`

---

### Task 4: FastAPI server（上传/元数据/查询/重试/统计）

**Files:**
- Create: `youtube-system/app/server.py`

- [ ] **Step 1: 创建 app/server.py**

```python
"""FastAPI server: presigned uploads, metadata, enqueue, stats.

Video uploading flow (design doc): binary upload and metadata upload run
in parallel; metadata submission enqueues the transcoding task.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from app import database as db
from app import presign
from app.completion_consumer import run_consumer
from app.config import config
from app.models import UploadUrlRequest, UploadUrlResponse, VideoCreateRequest
from app.queue import create_client, push_task

logger = logging.getLogger(__name__)

_stop = asyncio.Event()
_consumer_task: asyncio.Task | None = None
_redis = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task, _redis
    Path(config.original_dir).mkdir(parents=True, exist_ok=True)
    Path(config.transcoded_dir).mkdir(parents=True, exist_ok=True)
    await db.init_db()
    _redis = create_client()
    _stop.clear()
    _consumer_task = asyncio.create_task(run_consumer(_stop))
    logger.info("API server started")
    yield
    _stop.set()
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    await _redis.aclose()
    logger.info("API server stopped")


app = FastAPI(title="YouTube Video Streaming System", version="1.0.0",
              lifespan=lifespan)


def _card(v: dict) -> dict:
    return {
        "id": v["id"],
        "title": v["title"],
        "status": v["status"],
        "duration_sec": v["duration_sec"],
        "width": v["width"],
        "height": v["height"],
        "thumbnail_url": (f"/media/{v['id']}/thumbnail.jpg"
                          if v["status"] == "ready" else None),
        "error_msg": v["error_msg"],
        "created_at": v["created_at"],
    }


@app.post("/api/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(req: UploadUrlRequest):
    """Pre-signed upload authorization (design doc: Safety Optimizations)."""
    try:
        data = presign.issue(req.filename, req.size)
    except presign.PresignError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UploadUrlResponse(**data)


@app.post("/api/upload/{token}")
async def upload_video(token: str, request: Request):
    """Stream the video binary into original storage (blob storage)."""
    try:
        entry = presign.consume(token)
    except presign.PresignError as e:
        raise HTTPException(status_code=403, detail=str(e))

    dest = Path(config.original_dir) / f"{entry['video_id']}.{entry['ext']}"
    size = 0
    try:
        with dest.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.max_upload_bytes:
                    raise HTTPException(status_code=413,
                                        detail="File exceeds 1GB limit")
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty upload")
    return {"status": "uploaded", "video_id": entry["video_id"], "size": size}


@app.post("/api/videos")
async def create_video(req: VideoCreateRequest):
    """Metadata upload (parallel with binary) + enqueue transcoding task."""
    from app.config import config as _c
    ext = presign.ext_of(req.filename)
    if ext not in _c.allowed_exts:
        raise HTTPException(status_code=400, detail="Unsupported file extension")
    original_path = f"{req.video_id}.{ext}"
    if not (Path(_c.original_dir) / original_path).exists():
        raise HTTPException(status_code=400, detail="Binary not uploaded yet")
    await db.insert_video(req.video_id, req.title, req.description, original_path)
    await push_task(_redis, {"video_id": req.video_id,
                             "original_path": original_path})
    return {"status": "queued", "video_id": req.video_id}


@app.get("/api/videos")
async def list_videos():
    videos = await db.list_videos()
    return {"videos": [_card(v) for v in videos]}


@app.get("/api/videos/{video_id}")
async def get_video(video_id: str):
    v = await db.get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    data = _card(v) | {"description": v["description"]}
    if v["status"] == "ready":
        data["stream_url"] = f"/media/{video_id}/master.m3u8"
        data["renditions"] = await db.get_renditions(video_id)
    return data


@app.post("/api/videos/{video_id}/retry")
async def retry_video(video_id: str):
    v = await db.get_video(video_id)
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    if v["status"] != "failed":
        raise HTTPException(status_code=400, detail="Only failed videos can be retried")
    await db.set_video_status(video_id, "pending")
    await push_task(_redis, {"video_id": video_id,
                             "original_path": v["original_path"]})
    return {"status": "queued", "video_id": video_id}


@app.get("/api/stats")
async def stats():
    workers = 0
    async for _ in _redis.scan_iter(match="worker:*", count=100):
        workers += 1
    return {
        "task_queue_depth": await _redis.llen(config.task_queue),
        "workers": workers,
        "videos_by_status": await db.count_by_status(),
    }
```

- [ ] **Step 2: 验证（启动 + smoke 测试，无 Redis 时 lifespan 会失败，故仅做导入验证；完整验证在 Task 9 Docker 阶段）**

Run: `.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'youtube-system'); from app import server; print('routes:', len(server.app.routes))"`
Expected: `routes: 9`（数量 ≥8 即可）

---

### Task 5: Worker 基础（config / preprocessor / task_worker）

**Files:**
- Create: `youtube-system/worker/__init__.py`（空文件）
- Create: `youtube-system/worker/config.py`
- Create: `youtube-system/worker/preprocessor.py`
- Create: `youtube-system/worker/task_worker.py`

- [ ] **Step 1: 创建 worker/config.py**

```python
"""Transcoder worker configuration."""
import os
import socket
from dataclasses import dataclass


@dataclass
class WorkerConfig:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    task_queue: str = "transcode:tasks"
    event_queue: str = "transcode:events"
    original_dir: str = os.getenv("ORIGINAL_DIR", "data/original")
    transcoded_dir: str = os.getenv("TRANSCODED_DIR", "data/transcoded")
    concurrency: int = int(os.getenv("CONCURRENCY", "2"))
    health_host: str = "0.0.0.0"
    health_port: int = int(os.getenv("HEALTH_PORT", "8001"))
    max_retries: int = 3
    instance_id: str = f"{socket.gethostname()}-{os.getpid()}"
```

- [ ] **Step 2: 创建 worker/preprocessor.py**

```python
"""Preprocessor: ffprobe metadata extraction and rendition planning.

Corresponds to the Preprocessor in the design doc's transcoding
architecture. GOP alignment is delegated to ffmpeg's -g/-keyint_min flags
in the encode command.
"""
import asyncio
import json
from pathlib import Path


class UnrecoverableError(Exception):
    """Non-recoverable error: stop processing (design doc error handling)."""


RENDITION_TARGETS = {
    "1080p": {"height": 1080, "bitrate_kbps": 5000},
    "720p": {"height": 720, "bitrate_kbps": 2800},
    "480p": {"height": 480, "bitrate_kbps": 1400},
}


async def probe(path: Path) -> dict:
    """Extract duration/width/height via ffprobe. Raises UnrecoverableError."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise UnrecoverableError(
            f"ffprobe failed: {stderr.decode(errors='ignore')[:200]}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise UnrecoverableError(f"Unreadable probe output: {e}")

    vstreams = [s for s in data.get("streams", [])
                if s.get("codec_type") == "video"]
    if not vstreams:
        raise UnrecoverableError("No video stream found")

    vs = vstreams[0]
    duration = float(data.get("format", {}).get("duration")
                     or vs.get("duration") or 0)
    return {
        "duration_sec": duration,
        "width": int(vs.get("width", 0)),
        "height": int(vs.get("height", 0)),
    }


def select_renditions(width: int, height: int) -> list[dict]:
    """Pick target renditions by source height, keeping aspect ratio."""
    if height <= 0 or width <= 0:
        raise UnrecoverableError("Invalid video dimensions")
    if height >= 1080:
        keys = ["1080p", "720p", "480p"]
    elif height >= 720:
        keys = ["720p", "480p"]
    else:
        keys = ["480p"]

    renditions = []
    for key in keys:
        target = RENDITION_TARGETS[key]
        w = max(2, round(width * target["height"] / height / 2) * 2)
        renditions.append({
            "resolution": key,
            "height": target["height"],
            "width": w,
            "bitrate_kbps": target["bitrate_kbps"],
        })
    return renditions
```

- [ ] **Step 3: 创建 worker/task_worker.py**

```python
"""Task worker: ffmpeg execution with retry (design doc: Task Workers)."""
import asyncio
import logging
from pathlib import Path

from worker.preprocessor import UnrecoverableError

logger = logging.getLogger(__name__)


class RecoverableError(Exception):
    """Transient failure eligible for retry with backoff."""


async def _run(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = stderr.decode(errors="ignore")[-300:]
        raise RecoverableError(f"command failed ({proc.returncode}): {tail}")


async def encode_rendition(src: Path, out_root: Path, rend: dict,
                           max_retries: int) -> dict:
    """Encode one rendition to HLS with retry/backoff. Returns result entry."""
    out_dir = out_root / rend["resolution"]
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist = out_dir / "playlist.m3u8"

    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", f"scale=-2:{rend['height']}",
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-g", "48", "-keyint_min", "48", "-sc_threshold", "0",  # GOP alignment
        "-c:a", "aac", "-b:a", "128k",
        "-hls_time", "4", "-hls_playlist_type", "vod",
        "-hls_segment_filename", str(out_dir / "seg_%03d.ts"),
        str(playlist),
    ]

    delay = 2
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            await _run(cmd)
            return {
                "resolution": rend["resolution"],
                "playlist_path": f"{rend['resolution']}/playlist.m3u8",
                "bitrate_kbps": rend["bitrate_kbps"],
            }
        except RecoverableError as e:
            last_err = e
            logger.warning("Encode %s attempt %d/%d failed: %s",
                           rend["resolution"], attempt, max_retries, e)
            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay *= 2
    raise UnrecoverableError(
        f"Encode {rend['resolution']} failed after {max_retries} attempts: {last_err}")


async def make_thumbnail(src: Path, out_root: Path) -> None:
    cmd = ["ffmpeg", "-y", "-ss", "0.5", "-i", str(src), "-vframes", "1",
           "-q:v", "3", str(out_root / "thumbnail.jpg")]
    try:
        await _run(cmd)
    except RecoverableError:
        logger.warning("Thumbnail generation failed for %s (non-fatal)", src.name)


def build_master_playlist(renditions: list[dict]) -> str:
    """Pure function: multi-bitrate master playlist, highest bandwidth first."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for r in sorted(renditions, key=lambda x: -x["bitrate_kbps"]):
        bandwidth = r["bitrate_kbps"] * 1000 + 128_000  # video + audio
        lines.append(
            f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},'
            f'RESOLUTION={r["width"]}x{r["height"]}')
        lines.append(f'{r["resolution"]}/playlist.m3u8')
    return "\n".join(lines) + "\n"
```

---

### Task 6: Worker 调度层（resource_manager / pipeline / main）

**Files:**
- Create: `youtube-system/worker/resource_manager.py`
- Create: `youtube-system/worker/pipeline.py`
- Create: `youtube-system/worker/main.py`

- [ ] **Step 1: 创建 worker/resource_manager.py**

```python
"""Resource Manager: bounds concurrent ffmpeg work (design doc).

- _semaphore: caps simultaneous ffmpeg processes (worker slot queue)
- running:    tracks in-flight encode tasks (design doc "running queue")
"""
import asyncio


class ResourceManager:
    def __init__(self, concurrency: int):
        self._semaphore = asyncio.Semaphore(concurrency)
        self.running: dict[str, asyncio.Task] = {}

    async def submit(self, task_id: str, coro) -> asyncio.Task:
        """Submit a coroutine; execution waits for a free slot."""

        async def _limited():
            async with self._semaphore:
                return await coro

        t = asyncio.create_task(_limited())
        self.running[task_id] = t
        t.add_done_callback(lambda _: self.running.pop(task_id, None))
        return t

    @property
    def active_count(self) -> int:
        return sum(1 for t in self.running.values() if not t.done())

    async def drain(self) -> None:
        """Wait for all running tasks (graceful shutdown)."""
        pending = [t for t in self.running.values() if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
```

- [ ] **Step 2: 创建 worker/pipeline.py**

```python
"""DAG scheduler: runs one video's DAG of stages (design doc: DAG Scheduler).

Stage 0: announce processing (metadata + rendition set) via event
Stage 1: thumbnail (fast, non-fatal on failure)
Stage 2: parallel per-resolution encodes (bounded by Resource Manager)
Final:   master.m3u8 + ready/failed event
"""
import asyncio
import json
import logging
import shutil
from pathlib import Path

from worker.preprocessor import UnrecoverableError, probe, select_renditions
from worker.task_worker import (RecoverableError, build_master_playlist,
                                encode_rendition, make_thumbnail)

logger = logging.getLogger(__name__)


async def _emit(redis, cfg, event: dict) -> None:
    await redis.lpush(cfg.event_queue, json.dumps(event))


async def process_video(task: dict, cfg, redis, rm) -> dict:
    """Run the full transcoding DAG. Returns the final event dict."""
    video_id = task["video_id"]
    src = Path(cfg.original_dir) / task["original_path"]
    out_root = Path(cfg.transcoded_dir) / video_id

    try:
        info = await probe(src)
        renditions = select_renditions(info["width"], info["height"])
    except UnrecoverableError as e:
        logger.warning("Video %s unrecoverable: %s", video_id, e)
        return {"video_id": video_id, "type": "failed", "error": str(e)}

    # Idempotent re-run: clear previous output
    shutil.rmtree(out_root, ignore_errors=True)
    out_root.mkdir(parents=True, exist_ok=True)

    # Stage 0: announce processing + rendition set
    await _emit(redis, cfg, {
        "video_id": video_id, "type": "processing",
        "duration_sec": info["duration_sec"],
        "width": info["width"], "height": info["height"],
        "renditions": [{"resolution": r["resolution"],
                        "bitrate_kbps": r["bitrate_kbps"]} for r in renditions],
    })

    # Stage 1 + Stage 2: thumbnail alongside bounded parallel encodes
    thumb = asyncio.create_task(make_thumbnail(src, out_root))
    encode_tasks = [
        await rm.submit(f"{video_id}:{r['resolution']}",
                        encode_rendition(src, out_root, r, cfg.max_retries))
        for r in renditions
    ]
    try:
        done = list(await asyncio.gather(*encode_tasks))
        await thumb
    except UnrecoverableError as e:
        return {"video_id": video_id, "type": "failed", "error": str(e)}
    except RecoverableError as e:  # defensive: should not escape encode_rendition
        return {"video_id": video_id, "type": "failed", "error": str(e)}

    (out_root / "master.m3u8").write_text(build_master_playlist(renditions))
    logger.info("Video %s transcoded: %s", video_id,
                [r["resolution"] for r in done])
    return {"video_id": video_id, "type": "ready", "renditions": done}
```

- [ ] **Step 3: 创建 worker/main.py**

```python
"""Transcoder worker entrypoint: task consumer + heartbeat + health server.

Usage: python -m worker.main
Scale: docker compose up --scale transcoder-worker=2
"""
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI

from worker.config import WorkerConfig
from worker.pipeline import process_video
from worker.resource_manager import ResourceManager

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15


async def heartbeat_loop(redis, cfg: WorkerConfig, stop: asyncio.Event) -> None:
    """Liveness key for /api/stats worker counting (TTL 60s)."""
    key = f"worker:{cfg.instance_id}"
    while not stop.is_set():
        try:
            await redis.set(key, "1", ex=60)
        except Exception:
            logger.exception("Heartbeat failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def consume_loop(redis, cfg: WorkerConfig, rm: ResourceManager,
                       stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            item = await redis.blpop(cfg.task_queue, timeout=3)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Redis error; retrying in 2s")
            await asyncio.sleep(2)
            continue
        if item is None:
            continue

        task = json.loads(item[1])
        logger.info("Received task for video %s", task["video_id"])
        try:
            event = await process_video(task, cfg, redis, rm)
        except Exception:
            logger.exception("Pipeline crashed for %s", task["video_id"])
            event = {"video_id": task["video_id"], "type": "failed",
                     "error": "internal worker error"}
        try:
            await redis.lpush(cfg.event_queue, json.dumps(event))
        except Exception:
            logger.exception("Failed to publish completion event")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = WorkerConfig()
    redis = aioredis.from_url(cfg.redis_url, decode_responses=True)
    rm = ResourceManager(cfg.concurrency)
    stop = asyncio.Event()

    health = FastAPI(title="transcoder-worker")

    @health.get("/health")
    async def health_check():
        return {"status": "ok", "active_encodes": rm.active_count,
                "instance": cfg.instance_id}

    uvi = uvicorn.Server(uvicorn.Config(
        health, host=cfg.health_host, port=cfg.health_port, log_level="warning"))
    uvi.install_signal_handlers = lambda: None  # we manage signals ourselves
    uvi_task = asyncio.create_task(uvi.serve())
    hb_task = asyncio.create_task(heartbeat_loop(redis, cfg, stop))
    consumer_task = asyncio.create_task(consume_loop(redis, cfg, rm, stop))
    logger.info("Worker %s started (concurrency=%d)",
                cfg.instance_id, cfg.concurrency)

    # Graceful shutdown on SIGTERM/SIGINT (Linux container). Windows dev
    # falls back to KeyboardInterrupt.
    try:
        import signal
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    except NotImplementedError:
        pass

    await stop.wait()
    logger.info("Shutting down: draining running encodes...")
    consumer_task.cancel()
    hb_task.cancel()
    await rm.drain()
    uvi.should_exit = True
    await uvi_task
    await redis.aclose()
    logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: 验证（导入检查）**

Run: `.\venv\Scripts\python.exe -c "import sys; sys.path.insert(0, r'youtube-system'); from worker import main, pipeline, resource_manager, preprocessor, task_worker; print('ok')"`
Expected: `ok`

---

### Task 7: Docker 与编排（Dockerfile / worker.Dockerfile / cdn / compose）

**Files:**
- Create: `youtube-system/.dockerignore`
- Create: `youtube-system/Dockerfile`
- Create: `youtube-system/worker.Dockerfile`
- Create: `youtube-system/cdn/nginx.conf`
- Create: `youtube-system/docker-compose.yml`

- [ ] **Step 1: 创建 .dockerignore**

```text
data/
frontend/
__pycache__/
**/__pycache__/
*.pyc
.git/
```

- [ ] **Step 2: 创建 Dockerfile（api-server）**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    --retries 10 --timeout 120 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: 创建 worker.Dockerfile（含 ffmpeg）**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    --retries 10 --timeout 120 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY worker ./worker

EXPOSE 8001
CMD ["python", "-m", "worker.main"]
```

- [ ] **Step 4: 创建 cdn/nginx.conf**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;

    # HLS manifests
    location ~ \.m3u8$ {
        add_header Access-Control-Allow-Origin *;
        add_header Cache-Control "no-cache";
        types { application/vnd.apple.mpegurl m3u8; }
    }

    # HLS segments
    location ~ \.ts$ {
        add_header Access-Control-Allow-Origin *;
        types { video/mp2t ts; }
    }

    # Thumbnails
    location ~ \.jpg$ {
        add_header Access-Control-Allow-Origin *;
        types { image/jpeg jpg jpeg; }
    }
}
```

- [ ] **Step 5: 创建 docker-compose.yml**

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: youtube-redis
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  api-server:
    build: .
    container_name: youtube-api
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DB_PATH=data/youtube.db
      - ORIGINAL_DIR=data/original
      - TRANSCODED_DIR=data/transcoded
    volumes:
      - ./data:/app/data
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  transcoder-worker:
    build:
      context: .
      dockerfile: worker.Dockerfile
    # No fixed host port: --scale transcoder-worker=N must be possible
    expose:
      - "8001"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"]
      interval: 15s
      timeout: 5s
      retries: 3
    environment:
      - REDIS_URL=redis://redis:6379/0
      - ORIGINAL_DIR=data/original
      - TRANSCODED_DIR=data/transcoded
      - CONCURRENCY=2
    volumes:
      - ./data:/app/data
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped

  cdn:
    image: nginx:alpine
    container_name: youtube-cdn
    ports:
      - "8003:80"
    volumes:
      - ./data/transcoded:/usr/share/nginx/html:ro
      - ./cdn/nginx.conf:/etc/nginx/conf.d/default.conf:ro

  frontend:
    build: ./frontend
    container_name: youtube-frontend
    ports:
      - "8080:80"
    depends_on:
      - api-server
      - cdn
    restart: unless-stopped
```

注意：transcoder-worker 不映射宿主机端口（`expose` 而非 `ports`），否则 `--scale` 时端口冲突。

- [ ] **Step 6: 验证（compose 配置解析 + 镜像构建；frontend 未建时先注释 frontend 服务或跳过）**

Run: `cd D:\StudyProjects\system-design-notes\youtube-system; docker compose config --quiet; echo compose-ok`
Expected: `compose-ok`（frontend 目录尚不存在时，将 frontend 服务暂时注释）

Run: `docker compose build api-server transcoder-worker`
Expected: 两个镜像构建成功（worker 镜像含 ffmpeg，约 200-400MB）

---

### Task 8: 前端基础（package / vite / 路由 / API 客户端 / App）

**Files:**
- Create: `youtube-system/frontend/package.json`
- Create: `youtube-system/frontend/vite.config.js`
- Create: `youtube-system/frontend/index.html`
- Create: `youtube-system/frontend/.dockerignore`
- Create: `youtube-system/frontend/src/main.js`
- Create: `youtube-system/frontend/src/router.js`
- Create: `youtube-system/frontend/src/api.js`
- Create: `youtube-system/frontend/src/App.vue`

- [ ] **Step 1: 创建 frontend/package.json**

```json
{
  "name": "youtube-frontend",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.4.0",
    "axios": "^1.7.0",
    "hls.js": "^1.5.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: 创建 frontend/vite.config.js**

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8003'
    }
  }
})
```

- [ ] **Step 3: 创建 frontend/index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>MyTube</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

- [ ] **Step 4: 创建 frontend/.dockerignore**

```text
node_modules/
dist/
```

- [ ] **Step 5: 创建 frontend/src/main.js**

```js
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'

createApp(App).use(router).mount('#app')
```

- [ ] **Step 6: 创建 frontend/src/router.js**

```js
import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'
import UploadView from './views/UploadView.vue'
import WatchView from './views/WatchView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/upload', component: UploadView },
    { path: '/watch/:id', component: WatchView },
  ],
})
```

- [ ] **Step 7: 创建 frontend/src/api.js**

```js
import axios from 'axios'

const client = axios.create({ baseURL: '/api' })

export const getUploadUrl = (data) => client.post('/upload-url', data)

export const uploadBinary = (token, file, onProgress) =>
  axios.post(`/api/upload/${token}`, file, {
    headers: { 'Content-Type': 'application/octet-stream' },
    onUploadProgress: onProgress
  })

export const createVideo = (data) => client.post('/videos', data)
export const listVideos = () => client.get('/videos')
export const getVideo = (id) => client.get(`/videos/${id}`)
export const retryVideo = (id) => client.post(`/videos/${id}/retry`)
export const getStats = () => client.get('/stats')
```

- [ ] **Step 8: 创建 frontend/src/style.css**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; background: #0f0f0f; color: #f1f1f1; }
button { cursor: pointer; }
```

- [ ] **Step 9: 创建 frontend/src/App.vue**

```vue
<template>
  <div class="app">
    <header class="navbar">
      <RouterLink to="/" class="logo">▶ MyTube</RouterLink>
      <RouterLink to="/upload" class="upload-btn">+ Upload</RouterLink>
    </header>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1.5rem;
  background: #181818;
  position: sticky;
  top: 0;
  z-index: 10;
}
.logo { color: #ff0000; font-weight: 700; font-size: 1.25rem; text-decoration: none; }
.upload-btn {
  background: #ff0000; color: white; padding: 0.5rem 1rem;
  border-radius: 18px; text-decoration: none; font-weight: 600;
}
.upload-btn:hover { background: #cc0000; }
.content { max-width: 1280px; margin: 0 auto; padding: 1.5rem; }
</style>
```

- [ ] **Step 10: 验证（npm 安装 + 构建）**

Run: `cd D:\StudyProjects\system-design-notes\youtube-system\frontend; npm install --registry=https://registry.npmmirror.com; npm run build`
Expected: `dist/` 生成，`vite build` 无报错（views 尚不存在会报错，故本步骤在 Task 9 之后执行；本任务先创建文件即可）

---

### Task 9: 前端三视图（Home / Upload / Watch）

**Files:**
- Create: `youtube-system/frontend/src/views/HomeView.vue`
- Create: `youtube-system/frontend/src/views/UploadView.vue`
- Create: `youtube-system/frontend/src/views/WatchView.vue`

- [ ] **Step 1: 创建 HomeView.vue**

```vue
<template>
  <div>
    <h2 class="page-title">Videos</h2>
    <div v-if="videos.length === 0" class="empty">
      No videos yet. <RouterLink to="/upload">Upload your first one!</RouterLink>
    </div>
    <div class="grid">
      <RouterLink v-for="v in videos" :key="v.id" :to="`/watch/${v.id}`" class="card">
        <div class="thumb">
          <img v-if="v.thumbnail_url" :src="v.thumbnail_url" alt="" />
          <span class="badge" :class="v.status">{{ v.status }}</span>
          <span v-if="v.duration_sec" class="duration">{{ fmtDuration(v.duration_sec) }}</span>
        </div>
        <div class="meta">
          <h3>{{ v.title }}</h3>
          <p v-if="v.status === 'failed'" class="error">{{ v.error_msg }}</p>
        </div>
      </RouterLink>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { listVideos } from '../api'

const videos = ref([])
let timer = null

async function refresh() {
  try {
    const res = await listVideos()
    videos.value = res.data.videos
  } catch (e) {
    console.error('Failed to load videos:', e)
  }
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 5000)
})
onUnmounted(() => clearInterval(timer))

function fmtDuration(s) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}
</script>

<style scoped>
.page-title { margin-bottom: 1rem; }
.empty { color: #aaa; padding: 3rem; text-align: center; }
.empty a { color: #3ea6ff; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 1.25rem;
}
.card { text-decoration: none; color: inherit; }
.thumb { position: relative; aspect-ratio: 16/9; background: #272727; border-radius: 12px; overflow: hidden; }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.badge {
  position: absolute; top: 8px; left: 8px;
  padding: 2px 10px; border-radius: 10px;
  font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
}
.badge.pending { background: #f1c232; color: #000; }
.badge.processing { background: #3ea6ff; color: #000; }
.badge.ready { background: #2ba640; color: #fff; }
.badge.failed { background: #e53935; color: #fff; }
.duration {
  position: absolute; bottom: 8px; right: 8px;
  background: rgba(0, 0, 0, 0.8); padding: 1px 6px; border-radius: 4px;
  font-size: 0.75rem;
}
.meta h3 { font-size: 0.95rem; margin-top: 0.6rem; line-height: 1.3; }
.error { color: #ff6b6b; font-size: 0.8rem; margin-top: 0.25rem; }
</style>
```

- [ ] **Step 2: 创建 UploadView.vue**

```vue
<template>
  <div class="upload-page">
    <h2>Upload Video</h2>

    <div
      class="dropzone"
      :class="{ dragging }"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
      @click="$refs.file.click()"
    >
      <input ref="file" type="file" accept="video/*" hidden @change="onFile" />
      <p v-if="!file">
        {{ dragging ? 'Drop it!' : 'Drag & drop a video here, or click to browse' }}
      </p>
      <p v-else>{{ file.name }} ({{ fmtSize(file.size) }})</p>
    </div>

    <form class="form" @submit.prevent="submit">
      <input v-model="title" placeholder="Title" required maxlength="200" />
      <textarea v-model="description" placeholder="Description" rows="3"></textarea>
      <button :disabled="!file || uploading">
        {{ uploading ? 'Uploading…' : 'Upload' }}
      </button>
    </form>

    <div v-if="progress > 0" class="progress">
      <div class="bar" :style="{ width: progress + '%' }"></div>
      <span>{{ progress }}%</span>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="doneMsg" class="done">{{ doneMsg }}</p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { getUploadUrl, uploadBinary, createVideo } from '../api'

const router = useRouter()
const file = ref(null)
const dragging = ref(false)
const title = ref('')
const description = ref('')
const progress = ref(0)
const uploading = ref(false)
const error = ref('')
const doneMsg = ref('')

function onDrop(e) {
  dragging.value = false
  const f = e.dataTransfer.files[0]
  if (f) file.value = f
}
function onFile(e) {
  file.value = e.target.files[0] || null
}
function fmtSize(b) {
  return (b / 1024 / 1024).toFixed(1) + ' MB'
}

async function submit() {
  error.value = ''
  doneMsg.value = ''
  uploading.value = true
  progress.value = 0
  try {
    const { data } = await getUploadUrl({
      filename: file.value.name,
      size: file.value.size
    })
    // Design doc: binary upload and metadata upload run in parallel
    await Promise.all([
      uploadBinary(data.token, file.value, (e) => {
        progress.value = Math.round((e.loaded / e.total) * 100)
      }),
      createVideo({
        video_id: data.video_id,
        title: title.value,
        description: description.value,
        filename: file.value.name
      })
    ])
    doneMsg.value = 'Upload complete! Transcoding started.'
    setTimeout(() => router.push('/'), 800)
  } catch (e) {
    error.value = e.response?.data?.detail || 'Upload failed'
  } finally {
    uploading.value = false
  }
}
</script>

<style scoped>
.upload-page { max-width: 640px; margin: 0 auto; }
h2 { margin-bottom: 1rem; }
.dropzone {
  border: 2px dashed #444; border-radius: 12px;
  padding: 3rem 1rem; text-align: center; color: #aaa;
  cursor: pointer; transition: border-color 0.2s, background 0.2s;
}
.dropzone.dragging { border-color: #3ea6ff; background: rgba(62, 166, 255, 0.08); }
.form { display: flex; flex-direction: column; gap: 0.75rem; margin-top: 1.25rem; }
.form input, .form textarea {
  background: #181818; border: 1px solid #333; border-radius: 8px;
  padding: 0.7rem 0.9rem; color: #f1f1f1; font: inherit; resize: vertical;
}
.form button {
  background: #ff0000; color: white; border: none;
  padding: 0.7rem; border-radius: 8px; font-weight: 600;
}
.form button:disabled { opacity: 0.5; cursor: not-allowed; }
.progress { display: flex; align-items: center; gap: 0.75rem; margin-top: 1rem; }
.progress .bar {
  height: 8px; background: #3ea6ff; border-radius: 4px;
  transition: width 0.2s; flex: 0 0 auto;
}
.progress { height: 8px; background: #272727; border-radius: 4px; position: relative; }
.progress .bar { position: absolute; inset: 0 auto 0 0; }
.progress span { position: absolute; top: 14px; left: 0; font-size: 0.8rem; color: #aaa; }
.error { color: #ff6b6b; margin-top: 0.75rem; }
.done { color: #2ba640; margin-top: 0.75rem; }
</style>
```

- [ ] **Step 3: 创建 WatchView.vue**

```vue
<template>
  <div v-if="video" class="watch">
    <div class="player-wrap">
      <video ref="player" controls playsinline></video>
      <div v-if="video.status === 'processing'" class="overlay">
        ⏳ Transcoding… this page refreshes automatically
      </div>
      <div v-else-if="video.status === 'failed'" class="overlay failed">
        <p>Transcoding failed: {{ video.error_msg }}</p>
        <button @click="retry">Retry</button>
      </div>
      <div v-else-if="video.status !== 'ready'" class="overlay">
        Waiting for a worker…
      </div>
    </div>

    <div class="below">
      <div class="head">
        <h1>{{ video.title }}</h1>
        <div v-if="qualities.length" class="quality">
          <span>Quality:</span>
          <button
            v-for="(q, i) in qualities"
            :key="i"
            :class="{ on: currentLevel === i }"
            @click="setQuality(i)"
          >{{ q }}</button>
          <button :class="{ on: currentLevel === -1 }" @click="setQuality(-1)">Auto</button>
        </div>
      </div>
      <p v-if="video.description" class="desc">{{ video.description }}</p>
      <p v-if="video.duration_sec" class="meta">
        {{ fmtDuration(video.duration_sec) }} · {{ video.width }}×{{ video.height }}
      </p>
      <ul v-if="video.renditions && video.renditions.length" class="renditions">
        <li v-for="r in video.renditions" :key="r.resolution">
          {{ r.resolution }} — {{ r.status }} ({{ r.bitrate_kbps }} kbps)
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import Hls from 'hls.js'
import { getVideo, retryVideo } from '../api'

const route = useRoute()
const video = ref(null)
const player = ref(null)
const qualities = ref([])
const currentLevel = ref(-1)
let hls = null
let timer = null

async function load() {
  try {
    const { data } = await getVideo(route.params.id)
    video.value = data
    if (data.status === 'ready') {
      await nextTick()
      setupPlayer(data.stream_url)
      if (timer) { clearInterval(timer); timer = null }
    } else if (!timer) {
      timer = setInterval(load, 3000)
    }
  } catch (e) {
    console.error('Failed to load video:', e)
  }
}

function setupPlayer(url) {
  const el = player.value
  if (!el || hls) return
  if (Hls.isSupported()) {
    hls = new Hls()
    hls.loadSource(url)
    hls.attachMedia(el)
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      qualities.value = hls.levels.map((l) => (l.height ? `${l.height}p` : '??'))
      el.play().catch(() => {})
    })
  } else if (el.canPlayType('application/vnd.apple.mpegurl')) {
    el.src = url // Safari native HLS
  }
}

function setQuality(i) {
  if (!hls) return
  hls.currentLevel = i
  currentLevel.value = i
}

async function retry() {
  await retryVideo(route.params.id)
  load()
}

onMounted(load)
onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (hls) hls.destroy()
})

function fmtDuration(s) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}
</script>

<style scoped>
.player-wrap { position: relative; background: #000; border-radius: 12px; overflow: hidden; }
video { width: 100%; aspect-ratio: 16/9; display: block; }
.overlay {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; gap: 1rem;
  align-items: center; justify-content: center;
  background: rgba(0, 0, 0, 0.75); color: #ddd; font-size: 1rem;
}
.overlay.failed button {
  background: #ff0000; color: white; border: none;
  padding: 0.5rem 1.25rem; border-radius: 18px; font-weight: 600;
}
.head {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 0.75rem; margin-top: 1rem;
}
.head h1 { font-size: 1.25rem; }
.quality { display: flex; gap: 0.4rem; align-items: center; color: #aaa; font-size: 0.85rem; }
.quality button {
  background: #272727; color: #ddd; border: none;
  padding: 0.25rem 0.7rem; border-radius: 12px; font-size: 0.8rem;
}
.quality button.on { background: #3ea6ff; color: #000; font-weight: 600; }
.desc { color: #ccc; margin-top: 0.75rem; }
.meta { color: #888; font-size: 0.85rem; margin-top: 0.5rem; }
.renditions { list-style: none; margin-top: 0.75rem; color: #888; font-size: 0.8rem; }
.renditions li { padding: 2px 0; }
</style>
```

- [ ] **Step 4: 验证（npm install + build）**

Run: `cd D:\StudyProjects\system-design-notes\youtube-system\frontend; npm install --registry=https://registry.npmmirror.com; npm run build`
Expected: `vite build` 成功生成 `dist/`

---

### Task 10: 前端容器化 + 全栈构建部署

**Files:**
- Create: `youtube-system/frontend/Dockerfile`
- Create: `youtube-system/frontend/nginx.conf`

- [ ] **Step 1: 创建 frontend/Dockerfile**

```dockerfile
FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 2: 创建 frontend/nginx.conf**

```nginx
server {
    listen 80;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://api-server:8000;
        proxy_set_header Host $host;
        client_max_body_size 1024m;
    }

    location /media/ {
        proxy_pass http://cdn:80;
        proxy_set_header Host $host;
    }
}
```

注意：`client_max_body_size 1024m` 必须设置，否则大文件上传会被 nginx 以 413 拒绝。

- [ ] **Step 3: 全栈构建启动（worker 扩 2 副本）**

Run: `cd D:\StudyProjects\system-design-notes\youtube-system; docker compose up --build -d --scale transcoder-worker=2`
Expected: 6 个容器运行（redis, api-server, transcoder-worker-1/2, cdn, frontend）

Run: `docker compose ps`
Expected: 全部 Up/healthy

- [ ] **Step 4: 提交**

```bash
git add youtube-system/ docs/superpowers/plans/2026-09-17-youtube-video-streaming.md
git commit -m "feat(youtube): video streaming system (upload/transcode/HLS/CDN)"
```

---

### Task 11: 端到端验证 + README

**Files:**
- Create: `youtube-system/README.md`

- [ ] **Step 1: 生成测试视频（在 worker 容器内，其含 ffmpeg；产物经共享卷落盘宿主机）**

Run: `docker exec youtube-transcoder-worker-1 ffmpeg -y -f lavfi -i testsrc=duration=10:size=1920x1080:rate=30 -f lavfi -i sine=frequency=440:duration=10 -c:v libx264 -pix_fmt yuv420p -c:a aac /app/data/original/sample.mp4`
Expected: `./data/original/sample.mp4` 出现在宿主机

- [ ] **Step 2: 预签名 → 上传 → 提交元数据（PowerShell）**

```powershell
cd D:\StudyProjects\system-design-notes\youtube-system
$body = @{filename="sample.mp4"; size=1} | ConvertTo-Json
$resp = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/upload-url -ContentType "application/json" -Body $body
$resp | ConvertTo-Json   # 应含 token / video_id / upload_path / expires_in

curl.exe -s -X POST --data-binary "@data/original/sample.mp4" -H "Content-Type: application/octet-stream" "http://localhost:8000/api/upload/$($resp.token)"

$meta = @{video_id=$resp.video_id; title="Test Video"; description="e2e demo"; filename="sample.mp4"} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/videos -ContentType "application/json" -Body $meta
```

Expected: 上传返回 `status=uploaded`，元数据返回 `status=queued`

- [ ] **Step 3: 轮询状态直到 ready（验证事件消费与转码 DAG）**

Run: `Invoke-RestMethod http://localhost:8000/api/videos/$($resp.video_id) | ConvertTo-Json -Depth 4`
Expected: 10~30 秒内 `status` 变为 `ready`，`stream_url=/media/{id}/master.m3u8`，`renditions` 含 1080p/720p/480p 且 status=done

- [ ] **Step 4: CDN 直连验证 HLS 产物**

Run: `curl.exe -s http://localhost:8003/media/$($resp.video_id)/master.m3u8`
Expected: 输出含 `#EXT-X-STREAM-INF` 三行（1080p/720p/480p）

Run: `curl.exe -s -o NUL -w "%{http_code}" http://localhost:8003/media/$($resp.video_id)/thumbnail.jpg`
Expected: `200`

- [ ] **Step 5: 失败路径验证（损坏文件 → failed → retry 恢复）**

```powershell
Set-Content -Path data\original\bad.mp4 -Value "not a real video" -NoNewline
$b = @{filename="bad.mp4"; size=15} | ConvertTo-Json
$r2 = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/upload-url -ContentType "application/json" -Body $b
curl.exe -s -X POST --data-binary "@data/original/bad.mp4" -H "Content-Type: application/octet-stream" "http://localhost:8000/api/upload/$($r2.token)"
$m2 = @{video_id=$r2.video_id; title="Broken"; description=""; filename="bad.mp4"} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/videos -ContentType "application/json" -Body $m2
Start-Sleep 15
Invoke-RestMethod http://localhost:8000/api/videos/$($r2.video_id) | ConvertTo-Json
# 期望 status=failed（ffprobe 不可恢复错误）
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/videos/$($r2.video_id)/retry
```

Expected: failed 状态出现 `error_msg`；retry 返回 `queued`（该文件仍会再次 failed，属预期——损坏文件不可恢复）

- [ ] **Step 6: 前端 UI 验证（人工）**

打开 `http://localhost:8080`：
1. 首页网格显示两个视频卡片（ready 绿标 / failed 红标，缩略图可见）
2. 点击 ready 视频进入播放页，视频自动播放
3. 画质菜单显示 1080p/720p/480p，点击切换无卡顿断流
4. Upload 页拖拽任意小视频上传，进度条到 100% 后跳转首页，状态徽章流转 pending→processing→ready

- [ ] **Step 7: 编写 README.md（沿用 notification-system/search-autocomplete 中文 README 模式：功能特性/架构图/组件表/快速开始/API 端点/设计要点/技术栈）**

内容要点：
- 功能特性：真实 ffmpeg 转码多分辨率 HLS、预签名上传、Redis 任务队列解耦、Worker 水平扩展（--scale）、DAG 分阶段转码、失败重试、CDN 模拟、HLS.js 画质切换
- 架构图：Client→API→Redis→Worker(ffmpeg)→CDN 流程 + 并行上传/元数据
- 快速开始：`cd youtube-system; docker compose up --build -d --scale transcoder-worker=2`；前端 http://localhost:8080；API http://localhost:8000/docs
- API 端点表（7 个端点）
- 设计要点映射设计文档章节（转码流水线四层、预签名 URL、消息队列解耦、错误分类）
- 技术栈

---

## 自审记录（计划完成后已检查）

1. **规格覆盖：** 规格 §3 五容器→Task 7；§4 数据模型→Task 1；§5 全部 7 端点→Task 2/4（upload-url, upload, videos, list, detail, retry, stats）；§6 四层转码→Task 5/6（preprocessor/task_worker/resource_manager/pipeline/main）；§7 CDN→Task 7；§8 前端三视图→Task 8/9；§9 错误处理→Task 5（重试/不可恢复）+ Task 4（token 403/413/400）+ pipeline 幂等清理；§10 验证→Task 11 全覆盖。无遗漏。
2. **占位符扫描：** 无 TBD/TODO；所有步骤含完整代码或确切命令。
3. **类型一致性：** `push_task(task: dict)` 与 worker 消费 `{"video_id", "original_path"}` 一致；事件字段 `renditions:[{resolution,bitrate_kbps}]`（processing）与 `[{resolution,playlist_path,bitrate_kbps}]`（ready）与 `replace_renditions`/`set_rendition_done` 参数一致；`select_renditions` 返回字段（resolution/height/width/bitrate_kbps）与 `encode_rendition`/`build_master_playlist` 使用字段一致。
