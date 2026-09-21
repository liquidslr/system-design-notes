"""
DNS Resolver — Converts domain names to IP addresses with caching.

Design doc: "Use a DNS cache to avoid repeated lookups."
"""
import asyncio
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

# Thread pool for synchronous DNS resolution (more reliable on Windows)
_executor = ThreadPoolExecutor(max_workers=10)


def _resolve_sync(domain: str) -> Optional[str]:
    """Synchronous DNS resolution (runs in thread pool)."""
    try:
        result = socket.getaddrinfo(domain, None, family=socket.AF_INET)
        if result:
            return result[0][4][0]
    except (socket.gaierror, OSError) as e:
        logger.debug(f"DNS resolution failed for {domain}: {e}")
    return None


class DNSResolver:
    """
    Async DNS resolver with TTL-based cache.
    Avoids repeated DNS lookups for the same domain.
    Uses thread pool for DNS resolution (more reliable than asyncio getaddrinfo on Windows).
    """

    def __init__(self, cache_ttl: int = 300):
        self.cache_ttl = cache_ttl
        # domain -> (ip, timestamp)
        self._cache: dict[str, tuple[str, float]] = {}
        self._hits = 0
        self._misses = 0

    async def resolve(self, domain: str) -> Optional[str]:
        """Resolve a domain to an IP address. Returns cached result if available."""
        # Check cache
        cached = self._cache.get(domain)
        if cached:
            ip, timestamp = cached
            if time.time() - timestamp < self.cache_ttl:
                self._hits += 1
                return ip
            else:
                del self._cache[domain]

        # Cache miss — resolve via thread pool
        self._misses += 1
        loop = asyncio.get_event_loop()
        ip = await loop.run_in_executor(_executor, _resolve_sync, domain)

        if ip:
            self._cache[domain] = (ip, time.time())
        return ip

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @property
    def stats(self) -> dict:
        return {
            "cache_size": self.cache_size,
            "hits": self._hits,
            "misses": self._misses,
        }
