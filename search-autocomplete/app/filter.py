"""
Suggestion filter for blocking unwanted or harmful autocomplete suggestions.

Maintains an in-memory set of blocked queries loaded from the database.
Applied before returning suggestions to users.
"""
import logging

from app import database as db

logger = logging.getLogger(__name__)


class SuggestionFilter:
    """Filters out blocked queries from autocomplete suggestions."""

    def __init__(self):
        self._blocked: set[str] = set()

    async def load(self) -> None:
        """Load blocked queries from database."""
        self._blocked = await db.get_all_filters()
        logger.info(f"Filter loaded: {len(self._blocked)} blocked queries")

    def is_blocked(self, query: str) -> bool:
        """Check if a query is blocked."""
        return query.lower().strip() in self._blocked

    def filter_suggestions(
        self, suggestions: list[tuple[str, int]]
    ) -> list[tuple[str, int]]:
        """Remove blocked queries from a suggestion list."""
        return [(q, f) for q, f in suggestions if not self.is_blocked(q)]

    async def add(self, query: str, reason: str = "inappropriate") -> None:
        """Add a query to the blocklist."""
        query = query.lower().strip()
        await db.add_filter(query, reason)
        self._blocked.add(query)
        logger.info(f"Filtered query: '{query}' (reason: {reason})")

    async def remove(self, query: str) -> bool:
        """Remove a query from the blocklist."""
        query = query.lower().strip()
        removed = await db.remove_filter(query)
        if removed:
            self._blocked.discard(query)
        return removed

    @property
    def count(self) -> int:
        return len(self._blocked)
