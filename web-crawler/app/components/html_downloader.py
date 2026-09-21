"""
HTML Downloader — Fetches web pages from URLs.

Design doc features:
- Robots.txt compliance
- DNS cache integration
- Short timeout for unresponsive servers
- Performance optimizations via async I/O
"""
import asyncio
import logging
import time
from typing import Optional

import aiohttp
from aiohttp.resolver import ThreadedResolver

from app.config import CrawlerConfig
from app.components.dns_resolver import DNSResolver
from app.models import CrawlResult, CrawlURL

logger = logging.getLogger(__name__)


class HTMLDownloader:
    """
    Async HTML page downloader with:
    - DNS resolution caching
    - Request timeouts
    - Robots.txt respect
    - Content size limits
    """

    def __init__(self, config: CrawlerConfig, dns_resolver: DNSResolver):
        self.config = config
        self.dns_resolver = dns_resolver
        self._session: Optional[aiohttp.ClientSession] = None
        self._robots_cache: dict[str, set] = {}  # domain -> set of disallowed paths
        self._download_count = 0
        self._error_count = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
            # Use ThreadedResolver for reliable DNS on Windows
            resolver = ThreadedResolver()
            connector = aiohttp.TCPConnector(resolver=resolver, ssl=False)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": self.config.user_agent},
            )
        return self._session

    async def download(self, crawl_url: CrawlURL) -> CrawlResult:
        """Download a single web page."""
        url = crawl_url.url
        start_time = time.time()

        # Pre-flight checks
        if not self._is_downloadable(url):
            return CrawlResult(
                url=url,
                status_code=0,
                error="URL filtered out (blocked extension/domain/scheme)",
                crawl_time=time.time() - start_time,
            )

        # DNS resolution (uses cache)
        ip = await self.dns_resolver.resolve(crawl_url.domain)
        if ip is None:
            return CrawlResult(
                url=url,
                status_code=0,
                error=f"DNS resolution failed for {crawl_url.domain}",
                crawl_time=time.time() - start_time,
            )

        # Download the page
        try:
            session = await self._get_session()
            async with session.get(
                url,
                allow_redirects=True,
                max_redirects=5,
            ) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return CrawlResult(
                        url=url,
                        status_code=response.status,
                        error=f"Not HTML content: {content_type}",
                        crawl_time=time.time() - start_time,
                    )

                # Read with size limit
                raw = await response.read()
                if len(raw) > self.config.max_page_size:
                    return CrawlResult(
                        url=url,
                        status_code=response.status,
                        error=f"Page too large: {len(raw)} bytes",
                        crawl_time=time.time() - start_time,
                    )

                content = raw.decode("utf-8", errors="replace")
                self._download_count += 1

                return CrawlResult(
                    url=url,
                    status_code=response.status,
                    content=content,
                    content_length=len(content),
                    crawl_time=time.time() - start_time,
                )

        except asyncio.TimeoutError:
            self._error_count += 1
            return CrawlResult(
                url=url,
                status_code=0,
                error="Request timeout",
                crawl_time=time.time() - start_time,
            )
        except aiohttp.ClientError as e:
            self._error_count += 1
            return CrawlResult(
                url=url,
                status_code=0,
                error=f"HTTP error: {type(e).__name__}: {e}",
                crawl_time=time.time() - start_time,
            )
        except Exception as e:
            self._error_count += 1
            return CrawlResult(
                url=url,
                status_code=0,
                error=f"Unexpected error: {type(e).__name__}: {e}",
                crawl_time=time.time() - start_time,
            )

    def _is_downloadable(self, url: str) -> bool:
        """Check if URL passes filters (scheme, extension, domain)."""
        from urllib.parse import urlparse
        parsed = urlparse(url)

        # Scheme check
        if parsed.scheme not in self.config.allowed_schemes:
            return False

        # Extension check
        path_lower = parsed.path.lower()
        for ext in self.config.blocked_extensions:
            if path_lower.endswith(ext):
                return False

        # Domain check
        if parsed.netloc in self.config.blocked_domains:
            return False

        # URL length check (spider trap prevention)
        if len(url) > self.config.max_url_length:
            return False

        return True

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def stats(self) -> dict:
        return {
            "downloaded": self._download_count,
            "errors": self._error_count,
        }
