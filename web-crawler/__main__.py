"""
Web Crawler — CLI Entry Point

Usage:
    python -m web_crawler                          # Crawl with default seeds
    python -m web_crawler --urls https://example.com https://example.org
    python -m web_crawler --max-pages 100 --workers 10
    python -m web_crawler --seed-file seeds.txt
"""
import argparse
import asyncio
import logging
import sys
import os

# Add project root (web-crawler/) to path so 'app' package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import CrawlerConfig
from app.models import Priority
from app.crawler import CrawlerEngine


# Default seed URLs for demonstration
DEFAULT_SEED_URLS = [
    "https://example.com",
    "https://httpbin.org/html",
    "http://info.cern.ch",
    "https://www.python.org",
]


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy loggers
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Web Crawler — Scalable web content discovery system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--urls", nargs="+", default=None,
        help="Seed URLs to start crawling from",
    )
    parser.add_argument(
        "--seed-file", type=str, default=None,
        help="File containing seed URLs (one per line)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=50,
        help="Maximum number of pages to crawl (default: 50)",
    )
    parser.add_argument(
        "--workers", type=int, default=10,
        help="Number of concurrent workers (default: 10)",
    )
    parser.add_argument(
        "--max-depth", type=int, default=3,
        help="Maximum crawl depth from seed URLs (default: 3)",
    )
    parser.add_argument(
        "--politeness-delay", type=float, default=1.0,
        help="Delay between requests to same host in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--no-robots", action="store_true",
        help="Disable robots.txt compliance",
    )
    parser.add_argument(
        "--output-dir", type=str, default="crawled_pages",
        help="Directory to store crawled pages (default: crawled_pages)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    return parser.parse_args()


def load_seed_urls(args) -> list[str]:
    """Load seed URLs from args or file."""
    if args.urls:
        return args.urls

    if args.seed_file:
        try:
            with open(args.seed_file, "r") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            if urls:
                return urls
        except FileNotFoundError:
            print(f"Error: Seed file not found: {args.seed_file}")
            sys.exit(1)

    return DEFAULT_SEED_URLS


async def main():
    args = parse_args()
    setup_logging(args.verbose)

    # Build config
    config = CrawlerConfig(
        max_workers=args.workers,
        max_pages_total=args.max_pages,
        max_depth=args.max_depth,
        politeness_delay=args.politeness_delay,
        respect_robots_txt=not args.no_robots,
        content_dir=args.output_dir,
    )

    # Load seed URLs
    seed_urls = load_seed_urls(args)

    print("=" * 60)
    print("  WEB CRAWLER")
    print("=" * 60)
    print(f"  Seed URLs:      {len(seed_urls)}")
    print(f"  Max pages:      {config.max_pages_total}")
    print(f"  Workers:        {config.max_workers}")
    print(f"  Max depth:      {config.max_depth}")
    print(f"  Politeness:     {config.politeness_delay}s delay")
    print(f"  Robots.txt:     {'Yes' if config.respect_robots_txt else 'No'}")
    print(f"  Output:         {config.content_dir}/")
    print(f"  Database:       {config.db_path}")
    print("=" * 60)
    print()

    for i, url in enumerate(seed_urls, 1):
        print(f"  Seed {i}: {url}")
    print()

    # Create and run crawler
    crawler = CrawlerEngine(config)
    await crawler.crawl(seed_urls, max_pages=config.max_pages_total)


if __name__ == "__main__":
    asyncio.run(main())
