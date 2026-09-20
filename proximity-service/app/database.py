"""
Business database — SQLite via aiosqlite.
Per chapter: relational DB is a good fit for the read-heavy workload.
"""
from __future__ import annotations

import time

import aiosqlite

from .config import ProximityConfig

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, config: ProximityConfig):
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

    async def insert(self, name: str, category: str, lat: float, lng: float, address: str) -> int:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cur = await self._db.execute(
            "INSERT INTO businesses(name,category,lat,lng,address,created_at) VALUES(?,?,?,?,?,?)",
            (name, category, lat, lng, address, now),
        )
        await self._db.commit()
        return cur.lastrowid

    async def get(self, business_id: int) -> dict | None:
        async with self._db.execute("SELECT * FROM businesses WHERE id=?", (business_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def update(self, business_id: int, fields: dict) -> bool:
        if not fields:
            return False
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [business_id]
        await self._db.execute(f"UPDATE businesses SET {cols} WHERE id=?", tuple(vals))
        await self._db.commit()
        return True

    async def delete(self, business_id: int) -> bool:
        cur = await self._db.execute("DELETE FROM businesses WHERE id=?", (business_id,))
        await self._db.commit()
        return cur.rowcount > 0

    async def all(self) -> list[dict]:
        async with self._db.execute("SELECT * FROM businesses") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def count(self) -> int:
        async with self._db.execute("SELECT COUNT(*) AS c FROM businesses") as cur:
            row = await cur.fetchone()
            return row["c"] if row else 0
