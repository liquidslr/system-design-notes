"""
Metadata Database — SQLite via aiosqlite.
Stores users, files, blocks, file_versions, upload_sessions, shares, notifications.
"""
from __future__ import annotations

import aiosqlite
from .config import DriveConfig

_SCHEMA = """\
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
"""


class Database:
    def __init__(self, config: DriveConfig):
        self._config = config
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._config.data_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._config.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # --- Generic helpers ---

    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self._db.execute(sql, params)
        await self._db.commit()

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        await self._db.executemany(sql, params_list)
        await self._db.commit()

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        async with self._db.execute(sql, params) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # --- Users ---

    async def insert_user(self, user_id: str, email: str, pwd_hash: str,
                          salt: str, quota_bytes: int, created_at: str):
        await self.execute(
            "INSERT INTO users(user_id,email,pwd_hash,salt,quota_bytes,used_bytes,created_at) VALUES(?,?,?,?,?,0,?)",
            (user_id, email, pwd_hash, salt, quota_bytes, created_at),
        )

    async def get_user_by_email(self, email: str) -> dict | None:
        return await self.fetch_one("SELECT * FROM users WHERE email=?", (email,))

    async def get_user_by_id(self, user_id: str) -> dict | None:
        return await self.fetch_one("SELECT * FROM users WHERE user_id=?", (user_id,))

    async def update_user_used_bytes(self, user_id: str, delta: int):
        await self.execute(
            "UPDATE users SET used_bytes = used_bytes + ? WHERE user_id=?",
            (delta, user_id),
        )

    # --- Files ---

    async def insert_file(self, file_id: str, user_id: str, name: str, path: str,
                          namespace: str, created_at: str, updated_at: str):
        await self.execute(
            "INSERT INTO files(file_id,user_id,name,path,namespace,latest_version,size,storage_class,status,created_at,updated_at) VALUES(?,?,?,?,?,0,0,'hot','pending',?,?)",
            (file_id, user_id, name, path, namespace, created_at, updated_at),
        )

    async def get_file(self, file_id: str) -> dict | None:
        return await self.fetch_one("SELECT * FROM files WHERE file_id=?", (file_id,))

    async def get_file_by_namespace_path(self, namespace: str, path: str) -> dict | None:
        return await self.fetch_one("SELECT * FROM files WHERE namespace=? AND path=?", (namespace, path))

    async def list_files_by_user(self, user_id: str) -> list[dict]:
        return await self.fetch_all("SELECT * FROM files WHERE user_id=? ORDER BY updated_at DESC", (user_id,))

    async def list_files_shared_with(self, user_id: str) -> list[dict]:
        return await self.fetch_all(
            "SELECT f.* FROM files f JOIN shares s ON f.file_id=s.file_id WHERE s.shared_with=?",
            (user_id,),
        )

    async def update_file_version(self, file_id: str, version_no: int, size: int,
                                  status: str, updated_at: str):
        await self.execute(
            "UPDATE files SET latest_version=?, size=?, status=?, updated_at=? WHERE file_id=?",
            (version_no, size, status, updated_at, file_id),
        )

    # --- Blocks ---

    async def insert_block(self, block_hash: str, size: int, created_at: str):
        await self.execute(
            "INSERT OR IGNORE INTO blocks(block_hash,size,ref_count,created_at) VALUES(?,?,1,?)",
            (block_hash, size, created_at),
        )

    async def increment_block_ref(self, block_hash: str):
        await self.execute(
            "UPDATE blocks SET ref_count=ref_count+1 WHERE block_hash=?", (block_hash,)
        )

    async def decrement_block_ref(self, block_hash: str):
        await self.execute(
            "UPDATE blocks SET ref_count=ref_count-1 WHERE block_hash=?", (block_hash,)
        )

    async def get_block(self, block_hash: str) -> dict | None:
        return await self.fetch_one("SELECT * FROM blocks WHERE block_hash=?", (block_hash,))

    async def get_zero_ref_blocks(self) -> list[dict]:
        return await self.fetch_all("SELECT * FROM blocks WHERE ref_count<=0")

    async def delete_block_meta(self, block_hash: str):
        await self.execute("DELETE FROM blocks WHERE block_hash=?", (block_hash,))

    async def count_blocks(self) -> int:
        row = await self.fetch_one("SELECT COUNT(*) as cnt FROM blocks")
        return row["cnt"] if row else 0

    async def sum_block_sizes(self) -> int:
        row = await self.fetch_one("SELECT COALESCE(SUM(size),0) as total FROM blocks")
        return row["total"] if row else 0

    # --- File Versions ---

    async def insert_version(self, version_id: str, file_id: str, version_no: int,
                             block_hashes_json: str, size: int, author_id: str, created_at: str):
        await self.execute(
            "INSERT INTO file_versions(version_id,file_id,version_no,block_hashes,size,author_id,created_at) VALUES(?,?,?,?,?,?,?)",
            (version_id, file_id, version_no, block_hashes_json, size, author_id, created_at),
        )

    async def get_versions_for_file(self, file_id: str) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM file_versions WHERE file_id=? ORDER BY version_no DESC", (file_id,)
        )

    async def get_version(self, file_id: str, version_no: int) -> dict | None:
        return await self.fetch_one(
            "SELECT * FROM file_versions WHERE file_id=? AND version_no=?", (file_id, version_no)
        )

    # --- Upload Sessions ---

    async def create_session(self, session_id: str, file_id: str, uploader_id: str,
                             total_block_count: int, created_at: str, updated_at: str):
        await self.execute(
            "INSERT INTO upload_sessions(session_id,file_id,uploader_id,total_block_count,received_hashes,state,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)",
            (session_id, file_id, uploader_id, total_block_count, "[]", created_at, updated_at),
        )

    async def get_session(self, session_id: str) -> dict | None:
        return await self.fetch_one("SELECT * FROM upload_sessions WHERE session_id=?", (session_id,))

    async def update_session(self, session_id: str, received_hashes_json: str,
                             state: str, updated_at: str):
        await self.execute(
            "UPDATE upload_sessions SET received_hashes=?, state=?, updated_at=? WHERE session_id=?",
            (received_hashes_json, state, updated_at, session_id),
        )

    # --- Shares ---

    async def insert_share(self, file_id: str, owner_id: str, shared_with: str,
                           permission: str, created_at: str):
        await self.execute(
            "INSERT OR REPLACE INTO shares(file_id,owner_id,shared_with,permission,created_at) VALUES(?,?,?,?,?)",
            (file_id, owner_id, shared_with, permission, created_at),
        )

    async def get_share(self, file_id: str, shared_with: str) -> dict | None:
        return await self.fetch_one(
            "SELECT * FROM shares WHERE file_id=? AND shared_with=?", (file_id, shared_with)
        )

    # --- Notifications ---

    async def insert_notification(self, user_id: str, file_id: str, event: str,
                                  payload_json: str, created_at: str):
        await self.execute(
            "INSERT INTO notifications(user_id,file_id,event,payload,delivered,created_at) VALUES(?,?,?,?,0,?)",
            (user_id, file_id, event, payload_json, created_at),
        )

    async def get_undelivered_notifications(self, user_id: str, since_id: int) -> list[dict]:
        return await self.fetch_all(
            "SELECT * FROM notifications WHERE user_id=? AND notif_id>? AND delivered=0 ORDER BY notif_id",
            (user_id, since_id),
        )

    async def mark_notifications_delivered(self, ids: list[int]):
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        await self.execute(
            f"UPDATE notifications SET delivered=1 WHERE notif_id IN ({placeholders})",
            tuple(ids),
        )

    # --- Stats ---

    async def count_users(self) -> int:
        row = await self.fetch_one("SELECT COUNT(*) as cnt FROM users")
        return row["cnt"] if row else 0

    async def count_files(self) -> int:
        row = await self.fetch_one("SELECT COUNT(*) as cnt FROM files")
        return row["cnt"] if row else 0

    async def sum_file_sizes(self) -> int:
        row = await self.fetch_one("SELECT COALESCE(SUM(size),0) as total FROM files WHERE status='uploaded'")
        return row["total"] if row else 0
