"""
Core data models for the web crawler.
"""
import hashlib
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional
from urllib.parse import urlparse


class Priority(IntEnum):
    """URL priority levels. Higher value = higher priority."""
    LOWEST = 0
    LOW = 1
    NORMAL = 2
    HIGH = 3
    HIGHEST = 4


@dataclass
class CrawlURL:
    """Represents a URL to be crawled."""
    url: str
    depth: int = 0
    priority: Priority = Priority.NORMAL
    parent_url: Optional[str] = None
    discovered_at: float = field(default_factory=time.time)

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc

    @property
    def scheme(self) -> str:
        return urlparse(self.url).scheme

    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        if isinstance(other, CrawlURL):
            return self.url == other.url
        return False


@dataclass
class CrawlResult:
    """Result of crawling a single page."""
    url: str
    status_code: int
    content: Optional[str] = None
    content_hash: Optional[str] = None
    title: Optional[str] = None
    extracted_urls: list[str] = field(default_factory=list)
    content_length: int = 0
    crawl_time: float = 0.0
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300 and self.content is not None

    def compute_hash(self) -> str:
        """Compute content hash for duplicate detection."""
        if self.content:
            self.content_hash = hashlib.sha256(self.content.encode("utf-8", errors="ignore")).hexdigest()
        return self.content_hash or ""


@dataclass
class DomainQueue:
    """
    Politeness queue for a single domain.
    Corresponds to the per-host FIFO queues (b1, b2, ... bn) in the design.
    """
    domain: str
    urls: list[CrawlURL] = field(default_factory=list)
    last_crawl_time: float = 0.0
    is_busy: bool = False

    @property
    def is_empty(self) -> bool:
        return len(self.urls) == 0

    def add(self, url: CrawlURL):
        self.urls.append(url)

    def pop(self) -> Optional[CrawlURL]:
        if self.urls:
            return self.urls.pop(0)
        return None
