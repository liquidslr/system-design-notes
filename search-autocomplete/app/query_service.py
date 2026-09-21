"""
Query service — orchestrates trie lookup with filter application.

This is the main entry point for handling autocomplete queries.
"""
import logging
import re

from app.config import config
from app.trie import Trie
from app.filter import SuggestionFilter

logger = logging.getLogger(__name__)

# Precompiled pattern for validation
_VALID_PREFIX = re.compile(r"^[a-z\s]+$")


class QueryService:
    """Coordinates trie lookups with suggestion filtering."""

    def __init__(self, trie: Trie, suggestion_filter: SuggestionFilter):
        self.trie = trie
        self.filter = suggestion_filter

    def get_suggestions(self, prefix: str) -> list[dict]:
        """
        Get top-k autocomplete suggestions for a prefix.

        1. Validate and normalize the prefix
        2. Look up in trie
        3. Apply filter
        4. Return formatted results
        """
        prefix = prefix.lower().strip()[: config.max_prefix_length]

        if not prefix:
            return []

        if not _VALID_PREFIX.match(prefix):
            return []

        # Get cached suggestions from trie
        raw_suggestions = self.trie.search_prefix(prefix)

        # Apply filter
        filtered = self.filter.filter_suggestions(raw_suggestions)

        return [
            {"query": query, "frequency": freq}
            for query, freq in filtered[: config.top_k]
        ]
