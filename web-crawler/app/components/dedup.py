"""
Deduplication — Content Seen? and URL Seen? components.

Design doc:
- Content Seen?: "Checks for duplicate content using hash comparisons."
- URL Seen?: "Tracks visited URLs to avoid duplication."

Uses in-memory sets for URL dedup and content hash sets for content dedup.
For production scale (1B pages), a Bloom filter would be more memory-efficient.
"""
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class URLSeenTracker:
    """
    Tracks visited URLs to avoid re-crawling.
    Uses an in-memory set for O(1) lookups.
    """

    def __init__(self):
        self._seen_urls: set[str] = set()
        self._count = 0

    def is_seen(self, url: str) -> bool:
        return url in self._seen_urls

    def mark_seen(self, url: str):
        self._seen_urls.add(url)
        self._count += 1

    def mark_many(self, urls: list[str]):
        for url in urls:
            self._seen_urls.add(url)
        self._count += len(urls)

    @property
    def count(self) -> int:
        return self._count

    @property
    def size_mb(self) -> float:
        """Approximate memory usage in MB."""
        return len(self._seen_urls) * 200 / (1024 * 1024)


class ContentDeduplicator:
    """
    Detects duplicate content using SHA-256 hash comparison.
    "Content Seen?" component from the design.
    """

    def __init__(self):
        self._seen_hashes: set[str] = set()
        self._duplicate_count = 0

    def compute_hash(self, content: str) -> str:
        """Compute SHA-256 hash of content."""
        # Normalize: strip whitespace, lowercase for comparison
        normalized = content.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()

    def is_duplicate(self, content: str) -> bool:
        """Check if content has been seen before."""
        content_hash = self.compute_hash(content)
        if content_hash in self._seen_hashes:
            self._duplicate_count += 1
            return True
        return False

    def mark_seen(self, content: str) -> str:
        """Mark content as seen and return its hash."""
        content_hash = self.compute_hash(content)
        self._seen_hashes.add(content_hash)
        return content_hash

    def check_and_mark(self, content: str) -> tuple[bool, str]:
        """
        Check if content is duplicate and mark it as seen.
        Returns (is_duplicate, content_hash).
        """
        content_hash = self.compute_hash(content)
        is_dup = content_hash in self._seen_hashes
        if is_dup:
            self._duplicate_count += 1
        else:
            self._seen_hashes.add(content_hash)
        return is_dup, content_hash

    @property
    def unique_count(self) -> int:
        return len(self._seen_hashes)

    @property
    def duplicate_count(self) -> int:
        return self._duplicate_count
