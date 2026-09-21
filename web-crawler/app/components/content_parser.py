"""
Content Parser — Validates and parses HTML content.
URL Extractor — Extracts links from parsed HTML pages.
URL Filter — Excludes blacklisted or erroneous URLs.

Design doc:
- Content Parser: "Validates and parses web pages. Discards malformed pages."
- URL Extractor: "Extracts new links from parsed pages."
- URL Filter: "Excludes blacklisted or erroneous URLs."
"""
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.config import CrawlerConfig

logger = logging.getLogger(__name__)


class ContentParser:
    """
    Parses HTML content and extracts structured data.
    Discards malformed pages.
    """

    def parse(self, html: str) -> Optional[dict]:
        """
        Parse HTML content. Returns dict with title, text, links or None if malformed.
        """
        if not html or len(html.strip()) < 50:
            return None

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as e:
            logger.debug(f"Failed to parse HTML: {e}")
            return None

        # Extract title
        title = None
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

        # Extract text content (for future use / content mining)
        # Remove script and style elements
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)

        # Extract links
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                links.append(href)

        return {
            "title": title,
            "text": text,
            "links": links,
            "html_length": len(html),
        }


class URLExtractor:
    """
    Extracts and normalizes URLs from parsed HTML content.
    Converts relative URLs to absolute based on the parent page URL.
    """

    def __init__(self, config: CrawlerConfig):
        self.config = config

    def extract(self, parent_url: str, raw_links: list[str]) -> list[str]:
        """
        Extract valid URLs from raw links found in a page.
        Converts relative URLs to absolute, normalizes, and filters.
        """
        extracted = []
        seen = set()

        for raw_link in raw_links:
            try:
                # Convert relative to absolute
                absolute_url = urljoin(parent_url, raw_link)

                # Normalize: remove fragment, trailing slash
                parsed = urlparse(absolute_url)
                normalized = parsed._replace(fragment="").geturl()
                normalized = normalized.rstrip("/")

                # Filter
                if self._is_valid(normalized) and normalized not in seen:
                    seen.add(normalized)
                    extracted.append(normalized)

            except Exception:
                continue

        return extracted

    def _is_valid(self, url: str) -> bool:
        """Check if URL passes all filters."""
        parsed = urlparse(url)

        # Scheme check
        if parsed.scheme not in self.config.allowed_schemes:
            return False

        # Must have a netloc (domain)
        if not parsed.netloc:
            return False

        # Extension filter (URL Filter component)
        path_lower = parsed.path.lower()
        for ext in self.config.blocked_extensions:
            if path_lower.endswith(ext):
                return False

        # Domain blacklist
        if parsed.netloc in self.config.blocked_domains:
            return False

        # Spider trap prevention: URL length
        if len(url) > self.config.max_url_length:
            return False

        # Spider trap prevention: excessive path parameters
        if url.count(";") > 5 or url.count("?") > 3:
            return False

        return True


class URLFilter:
    """
    Additional URL filtering layer.
    Implements robots.txt compliance and custom rules.
    """

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self._robots_disallowed: dict[str, list[str]] = {}

    def is_allowed(self, url: str) -> bool:
        """Check if URL is allowed by all filter rules."""
        parsed = urlparse(url)

        # Check domain blacklist
        if parsed.netloc in self.config.blocked_domains:
            return False

        # Check blocked extensions
        path_lower = parsed.path.lower()
        for ext in self.config.blocked_extensions:
            if path_lower.endswith(ext):
                return False

        # Check URL length (spider trap)
        if len(url) > self.config.max_url_length:
            return False

        return True

    def set_robots_disallowed(self, domain: str, paths: list[str]):
        """Set disallowed paths from robots.txt for a domain."""
        self._robots_disallowed[domain] = paths

    def is_robots_allowed(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt rules."""
        if not self.config.respect_robots_txt:
            return True

        parsed = urlparse(url)
        domain = parsed.netloc
        path = parsed.path

        disallowed = self._robots_disallowed.get(domain, [])
        for disallowed_path in disallowed:
            if path.startswith(disallowed_path):
                return False

        return True
