"""
Async SQLite database layer for the Search Autocomplete System.

Manages three tables:
- query_logs: Raw user search queries
- frequencies: Aggregated query frequencies
- filter_list: Blocked/inappropriate queries
"""
import logging
import os
import time

import aiosqlite

from app.config import config

logger = logging.getLogger(__name__)

DB_PATH = config.db_path


async def init_db() -> None:
    """Create tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS query_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                timestamp REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS frequencies (
                query TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0,
                last_updated REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS filter_list (
                query TEXT PRIMARY KEY,
                reason TEXT NOT NULL DEFAULT 'inappropriate',
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON query_logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_freq_count ON frequencies(count DESC);
        """)
        await db.commit()
    logger.info("Database initialized")


async def log_query(query: str) -> None:
    """Record a raw user query in the log."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO query_logs (query, timestamp) VALUES (?, ?)",
            (query, time.time()),
        )
        await db.commit()


async def get_unaggregated_logs(last_aggregated_ts: float = 0) -> list[tuple[str, float]]:
    """Get query logs that haven't been aggregated yet."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT query, timestamp FROM query_logs WHERE timestamp > ? ORDER BY timestamp",
            (last_aggregated_ts,),
        )
        return await cursor.fetchall()


async def aggregate_frequencies(queries: dict[str, int]) -> None:
    """Update the frequencies table with new query counts."""
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        for query, count in queries.items():
            await db.execute(
                """INSERT INTO frequencies (query, count, last_updated)
                   VALUES (?, ?, ?)
                   ON CONFLICT(query) DO UPDATE SET
                     count = count + ?,
                     last_updated = ?""",
                (query, count, now, count, now),
            )
        await db.commit()


async def get_all_frequencies() -> dict[str, int]:
    """Get all aggregated query frequencies."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT query, count FROM frequencies")
        return {row[0]: row[1] for row in await cursor.fetchall()}


async def get_total_log_count() -> int:
    """Get total number of query logs."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM query_logs")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def add_filter(query: str, reason: str = "inappropriate") -> None:
    """Add a query to the filter list."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO filter_list (query, reason, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(query) DO UPDATE SET reason = ?, created_at = ?""",
            (query, reason, time.time(), reason, time.time()),
        )
        await db.commit()


async def remove_filter(query: str) -> bool:
    """Remove a query from the filter list. Returns True if it was present."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM filter_list WHERE query = ?", (query,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_all_filters() -> set[str]:
    """Get all filtered queries."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT query FROM filter_list")
        return {row[0] for row in await cursor.fetchall()}


async def get_filter_count() -> int:
    """Get total number of filtered queries."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM filter_list")
        row = await cursor.fetchone()
        return row[0] if row else 0
