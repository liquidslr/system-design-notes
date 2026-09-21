"""
Trie data structure with top-k cached suggestions at each node.

The trie stores search queries and their frequencies. Each node caches
the top-k most popular complete queries in its subtree, enabling O(1)
suggestion retrieval after prefix traversal.
"""
import logging
from app.config import config

logger = logging.getLogger(__name__)


class TrieNode:
    """A node in the trie."""

    __slots__ = ("children", "frequency", "is_end", "top_k")

    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.frequency: int = 0
        self.is_end: bool = False
        self.top_k: list[tuple[str, int]] = []


class Trie:
    """
    Trie with top-k caching at each node.

    - insert(query, freq): Insert or update a query's frequency
    - search_prefix(prefix): Return top-k suggestions for a prefix
    - delete(query): Remove a query from the trie
    - build_from_frequencies(freq_dict): Batch build from {query: freq}
    - rebuild_caches(): Recompute all top-k caches (bottom-up)
    """

    def __init__(self, k: int = None):
        self.root = TrieNode()
        self.k = k or config.top_k
        self._node_count = 0

    def insert(self, query: str, frequency: int = 1) -> None:
        """Insert a query with its frequency into the trie."""
        query = query.lower().strip()[: config.max_prefix_length]
        if not query or not all(c in config.allowed_chars or c == " " for c in query):
            return

        node = self.root
        for char in query:
            if char not in node.children:
                node.children[char] = TrieNode()
                self._node_count += 1
            node = node.children[char]

        node.is_end = True
        node.frequency = frequency
        # Caches will be rebuilt after batch insert

    def search_prefix(self, prefix: str) -> list[tuple[str, int]]:
        """
        Get top-k suggestions for a given prefix.

        Returns list of (query, frequency) tuples sorted by frequency desc.
        Uses cached top-k at the prefix node for O(1) retrieval.
        """
        prefix = prefix.lower().strip()[: config.max_prefix_length]
        if not prefix:
            return []

        node = self.root
        for char in prefix:
            if char not in node.children:
                return []
            node = node.children[char]

        return node.top_k[: self.k]

    def delete(self, query: str) -> bool:
        """Remove a query from the trie. Returns True if found and deleted."""
        query = query.lower().strip()
        if not query:
            return False

        # Navigate to the end node
        path = [self.root]
        node = self.root
        for char in query:
            if char not in node.children:
                return False
            node = node.children[char]
            path.append(node)

        if not node.is_end:
            return False

        # Remove the end marker
        node.is_end = False
        node.frequency = 0

        # Clean up empty nodes bottom-up
        for i in range(len(path) - 1, 0, -1):
            if not path[i].children and not path[i].is_end:
                del path[i - 1].children[query[i - 1]]
                self._node_count -= 1

        return True

    def build_from_frequencies(self, freq_dict: dict[str, int]) -> None:
        """
        Build the trie from a frequency dictionary.

        Clears existing data and rebuilds from scratch.
        After building, recomputes all top-k caches.
        """
        self.root = TrieNode()
        self._node_count = 0

        for query, freq in freq_dict.items():
            self.insert(query, freq)

        # Recompute all caches after batch insert
        self.rebuild_caches()
        logger.info(
            f"Trie built: {self._node_count} nodes from {len(freq_dict)} queries"
        )

    def rebuild_caches(self) -> None:
        """Recompute top-k caches for all nodes (bottom-up post-order traversal)."""
        self._compute_caches(self.root)

    def _compute_caches(self, node: TrieNode, prefix: str = "") -> list[tuple[str, int]]:
        """
        Recursively compute cached suggestions bottom-up.

        Returns the list of all (complete_query, frequency) pairs in this subtree.
        Sets node.top_k to the top-k of those pairs.
        """
        all_suggestions: list[tuple[str, int]] = []

        # If this node marks the end of a query, add it
        if node.is_end and node.frequency > 0:
            all_suggestions.append((prefix, node.frequency))

        # Recurse into children
        for char, child in node.children.items():
            child_suggestions = self._compute_caches(child, prefix + char)
            all_suggestions.extend(child_suggestions)

        # Sort by frequency desc, then alphabetically for ties
        all_suggestions.sort(key=lambda x: (-x[1], x[0]))
        node.top_k = all_suggestions[: self.k]

        return all_suggestions

    def get_stats(self) -> dict:
        """Return trie statistics."""
        total_freq = 0
        query_count = 0
        self._count_stats(self.root, "", total_freq, query_count)
        return {
            "nodes": self._node_count,
        }

    def _count_stats(self, node: TrieNode, prefix: str, total_freq: int, query_count: int) -> tuple[int, int]:
        """Recursively count stats."""
        if node.is_end:
            query_count += 1
            total_freq += node.frequency
        for char, child in node.children.items():
            query_count, total_freq = self._count_stats(child, prefix + char, total_freq, query_count)
        return query_count, total_freq

    def get_all_stats(self) -> dict:
        """Return comprehensive trie statistics."""
        qc, tf = self._count_stats(self.root, "", 0, 0)
        return {
            "trie_nodes": self._node_count,
            "total_queries": qc,
            "total_frequency": tf,
        }
