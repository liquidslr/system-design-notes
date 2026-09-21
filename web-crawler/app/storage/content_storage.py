"""
Content Storage — Stores crawled HTML pages and metadata.
URL Storage — Stores already visited URLs with metadata.

Design doc:
- Content Storage: "Stores HTML pages on disk (popular content in memory to reduce latency)."
- URL Storage: "Stores already visited URLs."

Uses SQLite for metadata and filesystem for HTML content storage.
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional

import aiosqlite

from app.config import CrawlerConfig
from app.models import CrawlResult

logger = logging.getLogger(__name__)


class ContentStorage:
    """
    Stores crawled HTML content to disk and metadata to SQLite.
    Popular content can be cached in memory for reduced latency.
    """

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._content_dir = config.content_dir
        self._db_path = config.db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._memory_cache: dict[str, str] = {}  # URL -> HTML (hot cache)
        self._cache_max_size = 1000
        self._stored_count = 0

    async def initialize(self):
        """Initialize storage: create directories and database tables."""
        os.makedirs(self._content_dir, exist_ok=True)

        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS crawled_pages (
                url TEXT PRIMARY KEY,
                title TEXT,
                content_hash TEXT,
                status_code INTEGER,
                content_length INTEGER,
                crawl_time REAL,
                crawled_at REAL,
                parent_url TEXT,
                depth INTEGER
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS crawl_stats (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await self._db.commit()

    async def store(self, result: CrawlResult, parent_url: str = "", depth: int = 0):
        """Store a crawled page: HTML to disk, metadata to SQLite."""
        if not result.is_success or not result.content:
            return

        # Store HTML to disk
        safe_filename = self._url_to_filename(result.url)
        filepath = os.path.join(self._content_dir, safe_filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(result.content)
        except Exception as e:
            logger.error(f"Failed to write content for {result.url}: {e}")
            return

        # Store metadata to SQLite
        try:
            await self._db.execute(
                """INSERT OR REPLACE INTO crawled_pages
                   (url, title, content_hash, status_code, content_length, crawl_time, crawled_at, parent_url, depth)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.url,
                    result.title,
                    result.content_hash,
                    result.status_code,
                    result.content_length,
                    result.crawl_time,
                    time.time(),
                    parent_url,
                    depth,
                ),
            )
            await self._db.commit()
        except Exception as e:
            logger.error(f"Failed to store metadata for {result.url}: {e}")
            return

        # Update memory cache
        self._memory_cache[result.url] = result.content
        if len(self._memory_cache) > self._cache_max_size:
            # Evict oldest entries
            keys_to_remove = list(self._memory_cache.keys())[:len(self._memory_cache) // 2]
            for k in keys_to_remove:
                del self._memory_cache[k]

        self._stored_count += 1

    def get_cached(self, url: str) -> Optional[str]:
        """Get content from memory cache (hot storage)."""
        return self._memory_cache.get(url)

    async def get_page_count(self) -> int:
        """Get total number of stored pages."""
        async with self._db.execute("SELECT COUNT(*) FROM crawled_pages") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def close(self):
        if self._db:
            await self._db.close()

    @staticmethod
    def _url_to_filename(url: str) -> str:
        """Convert URL to a safe filename using hash."""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        # Extract domain for readability
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace(":", "_").replace(".", "_")
        return f"{domain}_{url_hash}.html"

    @property
    def stats(self) -> dict:
        return {
            "stored": self._stored_count,
            "cache_size": len(self._memory_cache),
        }


class URLStorage:
    """
    Stores visited URLs with metadata for tracking and re-crawl decisions.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self, db: aiosqlite.Connection):
        """Use the same database connection as ContentStorage."""
        self._db = db
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS visited_urls (
                url TEXT PRIMARY KEY,
                status TEXT DEFAULT 'visited',
                discovered_at REAL,
                visited_at REAL,
                parent_url TEXT,
                depth INTEGER
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_visited_status ON visited_urls(status)
        """)
        await self._db.commit()

    async def mark_visited(self, url: str, parent_url: str = "", depth: int = 0):
        """Mark a URL as visited."""
        try:
            await self._db.execute(
                """INSERT OR REPLACE INTO visited_urls
                   (url, status, discovered_at, visited_at, parent_url, depth)
                   VALUES (?, 'visited', ?, ?, ?, ?)""",
                (url, time.time(), time.time(), parent_url, depth),
            )
            await self._db.commit()
        except Exception as e:
            logger.error(f"Failed to mark URL as visited: {url}: {e}")

    async def is_visited(self, url: str) -> bool:
        """Check if URL has been visited."""
        try:
            async with self._db.execute(
                "SELECT 1 FROM visited_urls WHERE url = ?", (url,)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None
        except Exception:
            return False

    async def get_visited_count(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM visited_urls") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
