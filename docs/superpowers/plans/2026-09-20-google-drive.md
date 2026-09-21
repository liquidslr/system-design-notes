# Google Drive (Cloud File Storage & Sync) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable Google Drive–style cloud storage system implementing content-addressed block storage, de-duplication, resumable upload, delta sync, conflict resolution, revision history, sharing, and long-polling notifications — in a single FastAPI process with SQLite + local filesystem.

**Architecture:** Single-process with internal role separation: an "object store" (filesystem blob store), a "block server" (splitting/hashing/dedup engine), and an "API service" (files, versions, upload sessions, sharing, sync/conflict, notifications). FastAPI routes are thin glue over api_service. A `drive-cli` client and scripted `--demo` provide E2E validation.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, aiosqlite, Pydantic v2, hashlib (SHA-256), httpx (test client), pytest + pytest-asyncio

**Spec reference:** `docs/superpowers/specs/2026-09-20-google-drive-design.md`

---

## File Structure

```
google-drive/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── object_store.py
│   ├── block_server.py
│   ├── models.py
│   ├── auth.py
│   ├── notification.py
│   ├── api_service.py
│   └── server.py
├── cli.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_object_store.py
│   ├── test_block_server.py
│   ├── test_upload_commit.py
│   ├── test_sync_conflict.py
│   ├── test_notification.py
│   └── test_integration.py
├── __main__.py
├── requirements.txt
└── README.md
```

---

### Task 1: Project Scaffolding & Configuration

**Files:**
- Create: `google-drive/app/__init__.py`
- Create: `google-drive/app/config.py`
- Create: `google-drive/requirements.txt`

- [ ] **Step 1: Create directory structure**

Create `google-drive/` and `google-drive/app/` with `__init__.py` (empty file).

- [ ] **Step 2: Write `google-drive/app/config.py`**

```python
"""Google Drive System Configuration — mirrors Chapter 15 design."""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DriveConfig:
    # --- Storage ---
    block_size: int = 4 * 1024 * 1024           # 4 MB per chapter spec
    default_quota_bytes: int = 10 * 1024**3     # 10 GB free tier
    max_file_size_bytes: int = 10 * 1024**3     # 10 GB max file
    max_versions_kept: int = 100                 # Revision cap per file

    # --- Paths ---
    data_dir: Path = field(default_factory=lambda: Path("data/google-drive"))
    db_filename: str = "drive_metadata.db"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 9200
    long_poll_timeout_sec: float = 30.0

    # Derived ---
    @property
    def blocks_dir(self) -> Path:
        return self.data_dir / "blocks"

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename
```

- [ ] **Step 3: Write `google-drive/requirements.txt`**

```
fastapi>=0.104
uvicorn>=0.24
aiosqlite>=0.19
pydantic>=2.5
httpx>=0.25
pytest>=7.4
pytest-asyncio>=0.23
```

- [ ] **Step 4: Verify imports**

Run: `cd google-drive && python -c "from app.config import DriveConfig; c=DriveConfig(); print(c.block_size)"`
Expected: `4194304`

- [ ] **Step 5: Commit**

```bash
git add google-drive/
git commit -m "feat(drive): project scaffolding and config"
```

---

### Task 2: Database Layer (SQLite Schema + CRUD)

**Files:**
- Create: `google-drive/app/database.py`
- Create: `google-drive/tests/__init__.py` (empty)
- Create: `google-drive/tests/test_database.py`

- [ ] **Step 1: Write the failing test for schema initialization**

```python
# tests/test_database.py
import pytest
import asyncio
from app.config import DriveConfig
from app.database import Database


@pytest.fixture
def config(tmp_path):
    cfg = DriveConfig()
    cfg.data_dir = tmp_path
    return cfg


@pytest.mark.asyncio
async def test_schema_created(config):
    db = Database(config)
    await db.initialize()
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = [r["name"] for r in tables]
    assert "users" in names
    assert "files" in names
    assert "blocks" in names
    assert "file_versions" in names
    assert "upload_sessions" in names
    assert "shares" in names
    assert "notifications" in names
    await db.close()
```

- [ ] **Step 2: Run test → FAIL (module not found)**

- [ ] **Step 3: Write `google-drive/app/database.py`**

Full implementation with:
- `class Database` holding `aiosqlite.Connection`
- `async initialize()` — creates all tables per spec schema (users, files, blocks, file_versions, upload_sessions, shares, notifications) with proper PK, UNIQUE constraints, and foreign keys
- Helper: `async execute(sql, params)`, `async fetch_one(sql, params)`, `async fetch_all(sql, params)`
- CRUD methods for each table (insert_user, get_user_by_email, insert_file, get_file, update_file_version, insert_block, get_block_hashes_missing, insert_version, get_versions_for_file, create_session, get_session, update_session_received, insert_share, get_share, insert_notification, get_undelivered_notifications, mark_delivered, get_stats)
- `async close()`

Schema SQL (embedded in `initialize()`):

```sql
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    pwd_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    quota_bytes INTEGER NOT NULL,
    used_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    namespace TEXT NOT NULL,
    latest_version INTEGER NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    storage_class TEXT NOT NULL DEFAULT 'hot',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(namespace, path)
);
CREATE TABLE IF NOT EXISTS blocks (
    block_hash TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    ref_count INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS file_versions (
    version_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    block_hashes TEXT NOT NULL,
    size INTEGER NOT NULL,
    author_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS upload_sessions (
    session_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    uploader_id TEXT NOT NULL,
    total_block_count INTEGER NOT NULL,
    received_hashes TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
    file_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    shared_with TEXT NOT NULL,
    permission TEXT NOT NULL DEFAULT 'view',
    created_at TEXT NOT NULL,
    PRIMARY KEY(file_id, shared_with)
);
CREATE TABLE IF NOT EXISTS notifications (
    notif_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    event TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    delivered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
```

- [ ] **Step 4: Run test → PASS**

Run: `cd google-drive && python -m pytest tests/test_database.py -v`

- [ ] **Step 5: Commit**

```bash
git add google-drive/app/database.py google-drive/tests/
git commit -m "feat(drive): database layer with full schema"
```

---

### Task 3: Object Store (Local Blob Store Simulating S3)

**Files:**
- Create: `google-drive/app/object_store.py`
- Create: `google-drive/tests/test_object_store.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_object_store.py
import pytest
from app.config import DriveConfig
from app.object_store import ObjectStore


@pytest.fixture
def store(tmp_path):
    cfg = DriveConfig()
    cfg.data_dir = tmp_path
    cfg.blocks_dir  # property auto-derived
    return ObjectStore(cfg)


def test_put_and_get(store):
    store.put("abc123", b"hello world")
    assert store.get("abc123") == b"hello world"


def test_exists(store):
    assert not store.exists("deadbeef")
    store.put("deadbeef", b"x")
    assert store.exists("deadbeef")


def test_delete(store):
    store.put("todelete", b"data")
    store.delete("todelete")
    assert not store.exists("todelete")


def test_put_if_absent_returns_false_if_exists(store):
    store.put("dup", b"first")
    was_new = store.put_if_absent("dup", b"second")
    assert was_new is False
    assert store.get("dup") == b"first"
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Write `app/object_store.py`**

```python
"""
Local content-addressed blob store simulating S3.
Blocks are stored at {blocks_dir}/{hash}. No hierarchy — pure key→bytes.
In production this would be Amazon S3 with cross-region replication.
"""
import shutil
from pathlib import Path
from .config import DriveConfig


class ObjectStore:
    def __init__(self, config: DriveConfig):
        self._root = config.blocks_dir
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._root / key

    def exists(self, key: str) -> bool:
        return self._path(key).file_ok() if hasattr(self._path(key), 'file_ok') else self._path(key).is_file()

    def put(self, key: str, data: bytes) -> None:
        self._path(key).write_bytes(data)

    def put_if_absent(self, key: str, data: bytes) -> bool:
        """Returns True if newly stored, False if already existed."""
        p = self._path(key)
        if p.is_file():
            return False
        p.write_bytes(data)
        return True

    def get(self, key: str) -> bytes | None:
        p = self._path(key)
        if p.is_file():
            return p.read_bytes()
        return None

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.is_file():
            p.unlink()

    def total_stored_bytes(self) -> int:
        return sum(f.stat().st_size for f in self._root.iterdir() if f.is_file())
```

- [ ] **Step 4: Run test → PASS**

- [ ] **Step 5: Commit**

```bash
git add google-drive/app/object_store.py google-drive/tests/test_object_store.py
git commit -m "feat(drive): object store (local S3 simulation)"
```

---

### Task 4: Block Server (Splitting, Hashing, Dedup Engine)

**Files:**
- Create: `google-drive/app/block_server.py`
- Create: `google-drive/tests/test_block_server.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_block_server.py
import hashlib
import pytest
from app.config import DriveConfig
from app.object_store import ObjectStore
from app.block_server import BlockServer


@pytest.fixture
def block_server(tmp_path):
    cfg = DriveConfig()
    cfg.data_dir = tmp_path
    cfg.block_size = 10  # small blocks for testing
    store = ObjectStore(cfg)
    return BlockServer(cfg, store)


def test_split_into_blocks(block_server):
    data = b"a" * 25  # 10 GB config → 10 byte test blocks → 3 blocks
    hashes, blocks = block_server.split(b"abc123")
    assert len(blocks) == 3


def test_store_and_check_dedup(block_server):
    chunk = b"hello"
    h = hashlib.sha256(chunk).hexdigest()
    stored_new = block_server.store_block(h, chunk)
    assert stored_new is True
    stored_again = block_server.store_block(h, chunk)
    assert stored_again is False  # dedup


def test_which_missing(block_server):
    chunk = b"exists"
    h = hashlib.sha256(chunk).hexdigest()
    block_server.store_block(h, chunk)
    other = hashlib.sha256(b"absent").hexdigest()
    missing = block_server.which_hashes_missing([h, other])
    assert missing == [other]
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Write `app/block_server.py`**

```python
"""
Block Server — splits data into fixed-size blocks, computes SHA-256,
stores via ObjectStore. Provides dedup/missing-hash queries.
No awareness of users or files — pure block mechanics.
"""
import hashlib
from .config import DriveConfig
from .object_store import ObjectStore


class BlockServer:
    def __init__(self, config: DriveConfig, store: ObjectStore):
        self._config = config
        self._store = store

    @staticmethod
    def compute_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def split(self, data: bytes) -> tuple[list[str], list[bytes]]:
        """Split data into blocks, return (hashes, raw_blocks)."""
        size = self._config.block_size
        blocks = [data[i:i + size] for i in range(0, len(data), size)] or [b""]
        hashes = [self.compute_hash(b) for b in blocks]
        return hashes, blocks

    def store_block(self, block_hash: str, data: bytes) -> bool:
        """Store block; verify hash integrity. Returns True if new, False if dedup hit."""
        if self.compute_hash(data) != block_hash:
            raise ValueError(f"Hash mismatch: expected {block_hash}")
        return self._store.put_if_absent(block_hash, data)

    def which_hashes_missing(self, hashes: list[str]) -> list[str]:
        """Return subset of hashes NOT yet in storage."""
        return [h for h in hashes if not self._store.exists(h)]

    def get_block(self, block_hash: str) -> bytes | None:
        return self._store.get(block_hash)

    def delete_block(self, block_hash: str) -> None:
        self._store.delete(block_hash)
```

- [ ] **Step 4: Run test → PASS**

- [ ] **Step 5: Commit**

```bash
git add google-drive/app/block_server.py google-drive/tests/test_block_server.py
git commit -m "feat(drive): block server with dedup engine"
```

---

### Task 5: Pydantic Models & Auth

**Files:**
- Create: `google-drive/app/models.py`
- Create: `google-drive/app/auth.py`

- [ ] **Step 1: Write `app/models.py`**

Define request/response models:
- `RegisterRequest(email, password)`, `LoginRequest(email, password)`, `AuthResponse(token, user_id)`
- `UploadStartRequest(file_name, path, size, total_block_count)`, `UploadStartResponse(session_id, file_id, deduplicated_hashes)`
- `BlockUploadRequest(session_id, blocks: list[{hash, data_b64}])`, `BlockUploadResponse(received_hashes)`
- `SessionStatusResponse(session_id, received_hashes, missing_count, state)`
- `CommitRequest(session_id, block_hashes)`, `CommitResponse(file_id, version_no)`
- `DownloadResponse(data_b64, file_name, size)`
- `RevisionItem(version_no, size, author_id, created_at)`
- `SyncRequest(states: list[{file_id, base_version, block_hashes}])`, `SyncResponse(updates, conflicts)`
- `ResolveRequest(action: 'override'|'keep', block_hashes?)`
- `ShareRequest(shared_with, permission)`
- `NotificationItem(notif_id, file_id, event, payload, created_at)`
- `StatsResponse(users, files, unique_blocks, logical_bytes, stored_bytes)`
- `FileInfo(file_id, name, path, size, latest_version, status, updated_at)`

- [ ] **Step 2: Write `app/auth.py`**

```python
"""Auth: register, login, token verification."""
import hashlib, secrets, time
from fastapi import Depends, HTTPException, Request
from .config import DriveConfig
from .database import Database

# In-memory token→user_id map (session store); comment: use Redis in production
_tokens: dict[str, str] = {}


async def register(db: Database, email: str, password: str) -> str:
    user_id = f"u_{secrets.token_hex(8)}"
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.insert_user(user_id, email, pwd_hash, salt, DriveConfig().default_quota_bytes, now)
    return user_id


async def login(db: Database, email: str, password: str) -> str | None:
    user = await db.get_user_by_email(email)
    if not user:
        return None
    pwd_hash = hashlib.sha256((password + user["salt"]).encode()).hexdigest()
    if pwd_hash != user["pwd_hash"]:
        return None
    token = secrets.token_hex(32)
    _tokens[token] = user["user_id"]
    return token


def get_current_user(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "")
    uid = _tokens.get(token)
    if not uid:
        raise HTTPException(401, "Unauthorized")
    return uid
```

- [ ] **Step 3: Commit**

```bash
git add google-drive/app/models.py google-drive/app/auth.py
git commit -m "feat(drive): models and auth"
```

---

### Task 6: Notification Center (Long Poll + Offline Queue)

**Files:**
- Create: `google-drive/app/notification.py`
- Create: `google-drive/tests/test_notification.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_notification.py
import asyncio
import pytest
from app.config import DriveConfig
from app.database import Database
from app.notification import NotificationCenter


@pytest.fixture
async def notif(tmp_path):
    cfg = DriveConfig()
    cfg.data_dir = tmp_path
    db = Database(cfg)
    await db.initialize()
    center = NotificationCenter(db)
    yield center
    await db.close()


@pytest.mark.asyncio
async def test_publish_and_consume(notif):
    await notif.publish("user1", "file1", "add", {"name": "test.txt"})
    events = await notif.poll("user1", since_id=0, wait=0.1)
    assert len(events) >= 1
    assert events[0]["file_id"] == "file1"


@pytest.mark.asyncio
async def test_long_poll_wakes(notif):
    async def delayed_publish():
        await asyncio.sleep(0.2)
        await notif.publish("user2", "file2", "edit", {})
    task = asyncio.create_task(delayed_publish())
    events = await notif.poll("user2", since_id=0, wait=2.0)
    assert len(events) == 1
    task.cancel()
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Write `app/notification.py`**

```python
"""
Notification center: in-process pub/sub + DB-backed offline queue.
Uses asyncio.Event to wake long-poll waiters immediately.
"""
import asyncio
import json
import time
from .database import Database


class NotificationCenter:
    def __init__(self, db: Database):
        self._db = db
        self._event = asyncio.Event()

    async def publish(self, user_id: str, file_id: str, event: str, payload: dict):
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self._db.insert_notification(user_id, file_id, event, json.dumps(payload), now)
        self._event.set()  # wake all waiters

    async def poll(self, user_id: str, since_id: int, wait: float) -> list[dict]:
        """Long-poll: return new events or block up to `wait` seconds."""
        deadline = time.monotonic() + wait
        while True:
            events = await self._db.get_undelivered_notifications(user_id, since_id)
            if events:
                ids = [e["notif_id"] for e in events]
                await self._db.mark_notifications_delivered(ids)
                return events
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            self._event.clear()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=min(remaining, 0.5))
            except asyncio.TimeoutError:
                pass  # re-check DB
```

- [ ] **Step 4: Run test → PASS**

- [ ] **Step 5: Commit**

```bash
git add google-drive/app/notification.py google-drive/tests/test_notification.py
git commit -m "feat(drive): notification center with long polling"
```

---

### Task 7: API Service (Upload/Commit/Sync/Conflict/Share/GC/Stats)

**Files:**
- Create: `google-drive/app/api_service.py`
- Create: `google-drive/tests/test_upload_commit.py`
- Create: `google-drive/tests/test_sync_conflict.py`

This is the core business logic. Key methods:
- `start_upload(user_id, file_name, path, size, total_block_count) → session_id, file_id, dedup_hashes`
- `upload_blocks(session_id, blocks: list[{hash, data}]) → received_hashes`
- `get_session_status(session_id) → received, missing_count, state`
- `commit(user_id, session_id, file_id, block_hashes) → version_no` (enforces quota, writes version, bumps ref_counts, publishes notification)
- `download(user_id, file_id, version?) → bytes` (checks ownership or share)
- `sync(user_id, states: list[{file_id, base_version, block_hashes}]) → updates, conflicts`
- `resolve(user_id, file_id, action, block_hashes?) → new_version_no`
- `share(user_id, file_id, shared_with, permission)`
- `list_revisions(file_id) → list[RevisionItem]`
- `garbage_collect() → freed_blocks_count`
- `get_stats() → stats dict`

- [ ] **Step 1: Write failing test for upload + commit + dedup**

```python
# tests/test_upload_commit.py
import pytest
from app.config import DriveConfig
from app.database import Database
from app.object_store import ObjectStore
from app.block_server import BlockServer
from app.notification import NotificationCenter
from app.api_service import ApiService


@pytest.fixture
async def svc(tmp_path):
    cfg = DriveConfig()
    cfg.data_dir = tmp_path
    cfg.block_size = 10
    db = Database(cfg)
    await db.initialize()
    store = ObjectStore(cfg)
    bs = BlockServer(cfg, store)
    nc = NotificationCenter(db)
    # Insert a test user
    await db.insert_user("u1", "a@b.c", "h", "s", 1024*1024, "2026-01-01")
    service = ApiService(cfg, db, bs, store, nc)
    yield service
    await db.close()


@pytest.mark.asyncio
async def test_full_upload_and_commit(svc):
    data = b"x" * 25  # 3 blocks of 10 bytes
    hashes, blocks = svc._block_server.split(data)
    session_id, file_id, dedup = await svc.start_upload("u1", "test.bin", "/test.bin", len(data), len(hashes))
    result = await svc.upload_blocks(session_id, [{"hash": h, "data": b64} for h, b64 in zip(hashes, [__import__('base64').b64encode(b).decode() for b in blocks])])
    version_no = await svc.commit("u1", session_id, file_id, hashes)
    assert version_no == 1
    downloaded = await svc.download("u1", file_id)
    assert downloaded == data


@pytest.mark.asyncio
async def test_dedup_across_files(svc):
    data = b"shared"
    h = svc._block_server.compute_hash(data)
    await svc.start_upload("u1", "f1", "/f1", len(data), 1)
    # store the block
    import base64
    await svc.upload_blocks_from_data(h, data)
    # second file with same content → no new block stored
    missing = svc._block_server.which_hashes_missing([h])
    assert missing == []
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Write `app/api_service.py`**

Implement all methods listed above. Key logic:
- `commit`: check all hashes exist via `which_hashes_missing` (must be empty); compute `new_unique_bytes` = only bytes for blocks that were new (ref_count incremented from 0→1); check `user.used_bytes + new_unique_bytes <= quota`; insert `file_version`, update `files.latest_version` + `used_bytes`; for each hash do `INSERT OR UPDATE blocks SET ref_count=ref_count+1`; publish notification.
- `sync`: for each `{file_id, base_version, block_hashes}`, if `server.latest_version == base_version` → OK (accept via commit); if `server > base_version` → conflict (store loser's hashes as pending, respond 409). For behind-files, return server's version metadata + block manifest.
- `resolve("override")` → promote stored conflict blocks to new version; `resolve("keep")` → return server's current block hashes.
- `garbage_collect()`: `DELETE FROM blocks WHERE ref_count=0` + remove from object store.

- [ ] **Step 4: Run tests → PASS**

- [ ] **Step 5: Write sync conflict test**

```python
# tests/test_sync_conflict.py
@pytest.mark.asyncio
async def test_conflict_both_versions_preserved(svc):
    # Upload initial file
    data1 = b"original"
    h1, b1 = svc._block_server.split(data1)
    sid, fid, _ = await svc.start_upload("u1", "doc", "/doc", len(data1), len(h1))
    await svc.upload_blocks_raw(sid, b1, h1)
    v1 = await svc.commit("u1", sid, fid, h1)

    # Client A edits (upload new version)
    dataA = b"editA"
    hA, bA = svc._block_server.split(dataA)
    sidA, _, _ = await svc.start_upload("u1", "doc", "/doc", len(dataA), len(hA), file_id=fid, base_version=v1)
    await svc.upload_blocks_raw(sidA, bA, hA)
    vA = await svc.commit("u1", sidA, fid, hA)

    # Client B edits (also based on v1) → should get conflict
    dataB = b"editB"
    hB, bB = svc._block_server.split(dataB)
    sidB, _, _ = await svc.start_upload("u1", "doc", "/doc", len(dataB), len(hB), file_id=fid, base_version=v1)
    await svc.upload_blocks_raw(sidB, bB, hB)
    with pytest.raises(ConflictError):
        await svc.commit("u1", sidB, fid, hB)

    # Both blocks stored in object_store
    assert svc._object_store.exists(hA[0])
    assert svc._object_store.exists(hB[0])

    # Resolve: override → client B version becomes new version
    vB = await svc.resolve("u1", fid, "override", hB)
    assert vB == vA + 1
```

- [ ] **Step 6: Run all tests → PASS**

- [ ] **Step 7: Commit**

```bash
git add google-drive/app/api_service.py google-drive/tests/test_upload_commit.py google-drive/tests/test_sync_conflict.py
git commit -m "feat(drive): core API service (upload/commit/sync/conflict/share/GC)"
```

---

### Task 8: FastAPI Server (Routes)

**Files:**
- Create: `google-drive/app/server.py`

- [ ] **Step 1: Write `app/server.py`**

Wire all endpoints from spec's API table to api_service. Use FastAPI's `lifespan` to init DB + object store + notification. Include all routers. Endpoints match spec exactly.

- [ ] **Step 2: Verify server starts**

Run: `cd google-drive && python -c "from app.server import app; print(app.title)"`

- [ ] **Step 3: Commit**

```bash
git add google-drive/app/server.py
git commit -m "feat(drive): FastAPI server routes"
```

---

### Task 9: CLI Client & Demo Entry Point

**Files:**
- Create: `google-drive/cli.py`
- Create: `google-drive/__main__.py`

- [ ] **Step 1: Write `cli.py`**

`argparse`-based CLI: `register`, `login`, `upload <filepath>`, `download <file_id> [output]`, `list`, `sync`, `share <file_id> <email> <perm>`, `revisions <file_id>`, `notifications`, `gc`, `stats`. Uses httpx calls to the running server.

- [ ] **Step 2: Write `__main__.py`**

- `--server`: start uvicorn
- `--demo`: run scripted story (2 users, multi-block upload, dedup proof, conflict + resolve, share + notification, GC, print stats)
- `--cli <args>`: forward to `cli.py`
- Default: run demo

- [ ] **Step 3: Commit**

```bash
git add google-drive/cli.py google-drive/__main__.py
git commit -m "feat(drive): CLI client and demo script"
```

---

### Task 10: Integration Test & Final Polish

**Files:**
- Create: `google-drive/tests/test_integration.py`
- Create: `google-drive/README.md`

- [ ] **Step 1: Write integration test**

Use FastAPI's `TestClient` + httpx to exercise the full HTTP flow: register → upload (multi-block) → verify dedup in stats → edit → conflict → resolve → share → download as sharee → notifications → GC. Verify byte-for-byte correctness of downloads.

- [ ] **Step 2: Run full test suite**

Run: `cd google-drive && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Write README.md**

Feature list, architecture summary, API table, how to run (server/demo/cli), how to test, design notes mapping to the chapter.

- [ ] **Step 4: Commit**

```bash
git add google-drive/tests/test_integration.py google-drive/README.md
git commit -m "feat(drive): integration tests and README"
```

---

### Task 11: Run Demo End-to-End

- [ ] **Step 1: Run `--demo`**

```bash
cd google-drive && python __main__.py --demo
```
Expected output: full storyline with "DEMO COMPLETE" and stats showing dedup savings.

- [ ] **Step 2: Verify all tasks checked + push (if requested)**

---

## Notes for Implementer

- **PowerShell**: use `;` not `&&` for command chaining; use single quotes for strings with colons in git commit messages.
- **Python version**: use `python -m pytest` from the `google-drive/` folder (ensure `sys.path` includes it, matching sibling subproject patterns in this repo).
- **ConflictError**: define a custom exception in `api_service.py`; server.py catches it → `HTTP 409`.
- **base64 encoding**: block data in JSON payloads is base64-encoded; decode server-side before storing.
- **ref_count decrement**: on `resolve("keep")` or file deletion, decrement ref_count for orphaned blocks. GC actually removes them.
- **Namespace**: use `namespace = "ns_{user_id}"` to echo the chapter's namespace model; files in shared folders keep owner's namespace.
