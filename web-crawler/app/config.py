"""
Web Crawler Configuration

Design doc references:
- Crawl 1 billion pages/month (~400 pages/sec, peak 800 QPS)
- HTML-only content
- Track new and updated pages
- Ignore duplicate content
- Store for 5 years
"""
from dataclasses import dataclass, field


@dataclass
class CrawlerConfig:
    # --- Concurrency ---
    max_workers: int = 50               # Number of parallel downloader workers
    max_pages_per_domain: int = 10      # Max concurrent requests per domain (politeness)
    politeness_delay: float = 1.0       # Seconds between requests to the same host

    # --- Limits ---
    max_pages_total: int = 10_000       # Total pages to crawl in this run (demo limit)
    max_url_length: int = 2048          # Spider trap prevention: max URL length
    max_depth: int = 5                  # Max crawl depth from seed URLs
    max_page_size: int = 10 * 1024 * 1024  # 10 MB max page size

    # --- Timeouts ---
    request_timeout: float = 10.0       # HTTP request timeout in seconds
    dns_cache_ttl: int = 300            # DNS cache TTL in seconds

    # --- Content ---
    allowed_schemes: set = field(default_factory=lambda: {"http", "https"})
    blocked_extensions: set = field(default_factory=lambda: {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
        ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".rar", ".tar", ".gz", ".7z",
        ".exe", ".dmg", ".apk", ".msi",
        ".css", ".js", ".woff", ".woff2", ".ttf", ".eot", ".ico",
    })
    blocked_domains: set = field(default_factory=lambda: set())

    # --- User Agent ---
    user_agent: str = "WebCrawler/1.0 (Educational; +https://example.com/bot)"
    respect_robots_txt: bool = True

    # --- Storage ---
    db_path: str = "crawler_data.db"
    content_dir: str = "crawled_pages"

    # --- Priority ---
    priority_levels: int = 5            # Number of priority queues (front queues)
