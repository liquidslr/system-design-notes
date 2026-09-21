"""
Five-Layer Cache Architecture for the News Feed System.

Design doc:
1. News Feed Cache: Stores post IDs for quick retrieval
2. Content Cache: Stores post details (popular posts in hot cache)
3. Social Graph Cache: Stores user relationship data
4. Action Cache: Tracks user actions (likes, replies, shares)
5. Counter Cache: Maintains counts for likes, replies, followers, etc.
"""
import logging
import time
from collections import OrderedDict
from typing import Optional, Any

from app.models import Post, FeedItem

logger = logging.getLogger(__name__)


class LRUCache:
    """Generic LRU cache with max size."""

    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            self._hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        self._misses += 1
        return None

    def set(self, key: str, value: Any):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def delete(self, key: str):
        self._cache.pop(key, None)

    def append_to_list(self, key: str, item: Any, max_list_len: int = 800):
        """Append item to a list stored at key."""
        lst = self._cache.get(key, [])
        lst.insert(0, item)  # Prepend (newest first)
        if len(lst) > max_list_len:
            lst = lst[:max_list_len]
        self._cache[key] = lst

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": self.size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self._hits / total * 100:.1f}%" if total > 0 else "0%",
        }


class CacheLayer:
    """
    Five-layer cache architecture.
    In production, use Redis/Memcached for each layer.
    """

    def __init__(self, config):
        # Layer 1: News Feed Cache — stores post IDs per user
        self.feed_cache = LRUCache(max_size=config.feed_cache_max_size)

        # Layer 2: Content Cache — stores full Post objects
        self.content_cache = LRUCache(max_size=config.content_cache_max_size)

        # Layer 3: Social Graph Cache — stores friend lists per user
        self.graph_cache = LRUCache(max_size=config.graph_cache_max_size)

        # Layer 4: Action Cache — stores actions per post
        self.action_cache = LRUCache(max_size=config.action_cache_max_size)

        # Layer 5: Counter Cache — stores counts per post/user
        self.counter_cache = LRUCache(max_size=config.counter_cache_max_size)

    # --- Layer 1: Feed Cache ---
    def get_feed(self, user_id: str) -> list[FeedItem]:
        return self.feed_cache.get(user_id) or []

    def add_to_feed(self, user_id: str, post_id: str, author_id: str, max_len: int = 800):
        item = FeedItem(post_id=post_id, user_id=author_id, created_at=time.time())
        self.feed_cache.append_to_list(user_id, item, max_list_len=max_len)

    def add_to_feed_batch(self, user_id: str, items: list[FeedItem], max_len: int = 800):
        existing = self.feed_cache.get(user_id) or []
        combined = items + existing
        if len(combined) > max_len:
            combined = combined[:max_len]
        self.feed_cache.set(user_id, combined)

    # --- Layer 2: Content Cache ---
    def get_post(self, post_id: str) -> Optional[Post]:
        return self.content_cache.get(post_id)

    def set_post(self, post: Post):
        self.content_cache.set(post.post_id, post)

    def set_posts(self, posts: list[Post]):
        for post in posts:
            self.content_cache.set(post.post_id, post)

    # --- Layer 3: Social Graph Cache ---
    def get_friends(self, user_id: str) -> Optional[list[str]]:
        return self.graph_cache.get(user_id)

    def set_friends(self, user_id: str, friend_ids: list[str]):
        self.graph_cache.set(user_id, friend_ids)

    # --- Layer 4: Action Cache ---
    def get_actions(self, post_id: str) -> Optional[list]:
        return self.action_cache.get(post_id)

    def set_actions(self, post_id: str, actions: list):
        self.action_cache.set(post_id, actions)

    # --- Layer 5: Counter Cache ---
    def get_counter(self, key: str) -> int:
        val = self.counter_cache.get(key)
        return val if val is not None else 0

    def set_counter(self, key: str, value: int):
        self.counter_cache.set(key, value)

    def increment_counter(self, key: str, delta: int = 1):
        current = self.get_counter(key)
        self.counter_cache.set(key, current + delta)

    @property
    def stats(self) -> dict:
        return {
            "feed_cache": self.feed_cache.stats,
            "content_cache": self.content_cache.stats,
            "graph_cache": self.graph_cache.stats,
            "action_cache": self.action_cache.stats,
            "counter_cache": self.counter_cache.stats,
        }
