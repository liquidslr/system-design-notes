"""
Crawler Engine — The main orchestrator that coordinates all components.

Implements the BFS traversal workflow from the design doc:
1. Seed URLs → URL Frontier
2. HTML Downloader fetches URLs (with DNS resolution)
3. Content Parser validates and parses
4. Content Seen? checks for duplicates
5. URL Extractor extracts new links
6. URL Filter excludes blacklisted URLs
7. New URLs → URL Frontier (BFS)
"""
import asyncio
import logging
import time
from typing import Optional

from app.config import CrawlerConfig
from app.models import CrawlResult, CrawlURL, Priority
from app.components.url_frontier import URLFrontier
from app.components.html_downloader import HTMLDownloader
from app.components.dns_resolver import DNSResolver
from app.components.content_parser import ContentParser, URLExtractor, URLFilter
from app.components.dedup import URLSeenTracker, ContentDeduplicator
from app.storage.content_storage import ContentStorage, URLStorage

logger = logging.getLogger(__name__)


class CrawlerEngine:
    """
    Main crawler engine that coordinates all components using BFS traversal.

    Architecture matches the design doc:
        Seed URLs → URL Frontier → HTML Downloader → Content Parser
            → Content Seen? → URL Extractor → URL Filter → URL Frontier
    """

    def __init__(self, config: Optional[CrawlerConfig] = None):
        self.config = config or CrawlerConfig()

        # Core components
        self.dns_resolver = DNSResolver(cache_ttl=self.config.dns_cache_ttl)
        self.frontier = URLFrontier(self.config)
        self.downloader = HTMLDownloader(self.config, self.dns_resolver)
        self.parser = ContentParser()
        self.url_extractor = URLExtractor(self.config)
        self.url_filter = URLFilter(self.config)

        # Deduplication
        self.url_seen = URLSeenTracker()
        self.content_dedup = ContentDeduplicator()

        # Storage
        self.content_storage = ContentStorage(self.config)
        self.url_storage = URLStorage(self.config.db_path)

        # State
        self._running = False
        self._pages_crawled = 0
        self._start_time = 0.0
        self._workers: list[asyncio.Task] = []

    async def initialize(self):
        """Initialize storage components."""
        await self.content_storage.initialize()
        await self.url_storage.initialize(self.content_storage._db)

    async def add_seed_urls(self, urls: list[str], priority: Priority = Priority.NORMAL):
        """Add seed URLs to start the crawl."""
        added = 0
        for url in urls:
            # Don't mark as seen here — the worker will mark after processing
            crawl_url = CrawlURL(url=url, depth=0, priority=priority)
            await self.frontier.enqueue(crawl_url)
            added += 1
        logger.info(f"Added {added} seed URLs to the frontier")

    async def crawl(self, seed_urls: list[str], max_pages: Optional[int] = None):
        """
        Run the crawler with given seed URLs.
        Uses BFS traversal with multiple async workers.
        """
        max_pages = max_pages or self.config.max_pages_total
        self._running = True
        self._start_time = time.time()

        await self.initialize()
        await self.add_seed_urls(seed_urls)

        # Start worker tasks
        num_workers = min(self.config.max_workers, max_pages)
        logger.info(f"Starting crawler with {num_workers} workers, max {max_pages} pages")

        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(num_workers)
        ]

        # Monitor progress
        await self._monitor(max_pages)

        # Stop workers
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

        await self.shutdown()
        self._print_final_report()

    async def _worker(self, worker_id: int):
        """
        Worker task: repeatedly dequeues URLs and processes them.
        Each worker follows the full pipeline:
            Download → Parse → Dedup → Extract → Filter → Enqueue
        """
        while self._running and self._pages_crawled < self.config.max_pages_total:
            # Get next URL from frontier
            crawl_url = await self.frontier.dequeue()
            if crawl_url is None:
                # Wait for more URLs or timeout
                if await self.frontier.wait_for_ready(timeout=2.0):
                    continue
                else:
                    break  # No more URLs to crawl

            # Process the URL through the pipeline
            await self._process_url(crawl_url)

    async def _process_url(self, crawl_url: CrawlURL):
        """Process a single URL through the full pipeline."""
        # Skip if depth exceeds max
        if crawl_url.depth > self.config.max_depth:
            return

        # Mark URL as seen before processing
        self.url_seen.mark_seen(crawl_url.url)

        # Step 1: Download HTML
        result = await self.downloader.download(crawl_url)

        if not result.is_success:
            if result.error:
                logger.debug(f"[{crawl_url.url}] Failed: {result.error}")
            return

        # Step 2: Parse content
        parsed = self.parser.parse(result.content)
        if parsed is None:
            logger.debug(f"[{crawl_url.url}] Malformed HTML, discarded")
            return

        result.title = parsed.get("title")

        # Step 3: Content Seen? (duplicate detection)
        is_duplicate, content_hash = self.content_dedup.check_and_mark(result.content)
        if is_duplicate:
            logger.debug(f"[{crawl_url.url}] Duplicate content, skipped")
            return
        result.content_hash = content_hash

        # Step 4: Store the page
        await self.content_storage.store(result, crawl_url.parent_url or "", crawl_url.depth)
        await self.url_storage.mark_visited(crawl_url.url, crawl_url.parent_url or "", crawl_url.depth)
        self._pages_crawled += 1

        logger.info(
            f"[{self._pages_crawled}] {crawl_url.url} "
            f"| title={result.title[:50] if result.title else 'N/A'} "
            f"| links={len(parsed['links'])} "
            f"| {result.crawl_time:.2f}s"
        )

        # Step 5: URL Extractor — extract links from parsed content
        extracted_urls = self.url_extractor.extract(crawl_url.url, parsed["links"])

        # Step 6: URL Filter + URL Seen? — filter and enqueue new URLs
        new_count = 0
        for url in extracted_urls:
            # URL Seen? check
            if self.url_seen.is_seen(url):
                continue

            # URL Filter check
            if not self.url_filter.is_allowed(url):
                continue

            # Mark as seen and enqueue
            self.url_seen.mark_seen(url)
            new_url = CrawlURL(
                url=url,
                depth=crawl_url.depth + 1,
                priority=self._compute_priority(url, crawl_url),
                parent_url=crawl_url.url,
            )
            await self.frontier.enqueue(new_url)
            new_count += 1

        if new_count > 0:
            logger.debug(f"[{crawl_url.url}] Discovered {new_count} new URLs")

    def _compute_priority(self, url: str, parent: CrawlURL) -> Priority:
        """
        Compute priority for a discovered URL (Prioritizer component).
        Simple heuristic: same-domain links get higher priority.
        """
        from urllib.parse import urlparse
        url_domain = urlparse(url).netloc
        parent_domain = urlparse(parent.url).netloc

        if url_domain == parent_domain:
            return Priority.HIGH  # Same domain = more important
        else:
            return Priority.NORMAL  # External link = normal priority

    async def _monitor(self, max_pages: int):
        """Monitor crawl progress and print periodic stats."""
        while self._running and self._pages_crawled < max_pages:
            await asyncio.sleep(5)
            elapsed = time.time() - self._start_time
            rate = self._pages_crawled / elapsed if elapsed > 0 else 0
            logger.info(
                f"--- Progress: {self._pages_crawled}/{max_pages} pages | "
                f"{rate:.1f} pages/sec | "
                f"Frontier: {self.frontier.pending_count} pending | "
                f"DNS cache: {self.dns_resolver.cache_size} entries | "
                f"Unique content: {self.content_dedup.unique_count} | "
                f"Duplicates: {self.content_dedup.duplicate_count} ---"
            )

            # Check if we should stop
            if self.frontier.pending_count == 0 and self._pages_crawled > 0:
                logger.info("Frontier is empty. Crawl complete.")
                break

    async def shutdown(self):
        """Clean up resources."""
        await self.downloader.close()
        await self.content_storage.close()

    def _print_final_report(self):
        """Print final crawl report."""
        elapsed = time.time() - self._start_time
        rate = self._pages_crawled / elapsed if elapsed > 0 else 0

        print("\n" + "=" * 60)
        print("CRAWL REPORT")
        print("=" * 60)
        print(f"  Total pages crawled:  {self._pages_crawled}")
        print(f"  Total time:           {elapsed:.1f}s")
        print(f"  Crawl rate:           {rate:.1f} pages/sec")
        print(f"  Unique content:       {self.content_dedup.unique_count}")
        print(f"  Duplicate content:    {self.content_dedup.duplicate_count}")
        print(f"  URLs seen:            {self.url_seen.count}")
        print(f"  DNS cache entries:    {self.dns_resolver.cache_size}")
        print(f"  DNS cache hits:       {self.dns_resolver.stats['hits']}")
        print(f"  Downloads:            {self.downloader.stats['downloaded']}")
        print(f"  Download errors:      {self.downloader.stats['errors']}")
        print(f"  Pages stored:         {self.content_storage.stats['stored']}")
        print("=" * 60)

    def get_stats(self) -> dict:
        """Get comprehensive crawler statistics."""
        return {
            "pages_crawled": self._pages_crawled,
            "frontier": self.frontier.stats,
            "downloader": self.downloader.stats,
            "dns": self.dns_resolver.stats,
            "content_dedup": {
                "unique": self.content_dedup.unique_count,
                "duplicates": self.content_dedup.duplicate_count,
            },
            "url_seen": {
                "count": self.url_seen.count,
                "memory_mb": round(self.url_seen.size_mb, 2),
            },
            "storage": self.content_storage.stats,
        }
