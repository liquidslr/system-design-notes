"""
News Feed Service — Core business logic.

Design doc flow:
- Feed Publishing: User → API → Post Service → DB + Cache → Fanout Service → Friends' feeds
- Feed Retrieval: User → API → Feed Service → Feed Cache (post IDs) → Content Cache (post details)
"""
import logging
import time
import uuid
from typing import Optional

from app.config import FeedConfig
from app.cache import CacheLayer
from app.database import Database
from app.fanout import FanoutService
from app.models import Post, PostType, Action, ActionType, User

logger = logging.getLogger(__name__)


class FeedService:
    """Core news feed service."""

    def __init__(self, config: FeedConfig, db: Database, cache: CacheLayer, fanout: FanoutService):
        self.config = config
        self.db = db
        self.cache = cache
        self.fanout = fanout

    # --- Publishing ---

    async def create_post(self, user_id: str, content: str, post_type: str = "text",
                          media_urls: list[str] = None) -> Post:
        """
        Publish a new post.
        Design doc: POST /v1/me/feed
        """
        post = Post(
            post_id=str(uuid.uuid4()),
            user_id=user_id,
            content=content,
            post_type=PostType(post_type),
            media_urls=media_urls or [],
            created_at=time.time(),
        )

        # Store in DB
        await self.db.create_post(post)

        # Cache the post (Layer 2: Content Cache)
        self.cache.set_post(post)

        # Fanout to friends' feeds (async)
        await self.fanout.fanout_post(post)

        # Also add to author's own feed
        self.cache.add_to_feed(user_id, post.post_id, user_id, self.config.max_feed_length)

        logger.info(f"Post created: {post.post_id[:8]} by {user_id}")
        return post

    # --- Feed Retrieval ---

    async def get_feed(self, user_id: str, page: int = 0, page_size: int = None) -> list[Post]:
        """
        Get user's news feed.
        Design doc: GET /v1/me/feed
        Feed is built from Layer 1 (Feed Cache) + Layer 2 (Content Cache) + DB fallback.
        """
        page_size = page_size or self.config.feed_page_size

        # Layer 1: Get post IDs from Feed Cache
        feed_items = self.cache.get_feed(user_id)

        if not feed_items:
            # Cache miss — build feed from DB (pull model / cold start)
            feed_items = await self._build_feed_from_db(user_id)

        # Paginate
        start = page * page_size
        end = start + page_size
        page_items = feed_items[start:end]

        if not page_items:
            return []

        # Layer 2: Get full post details from Content Cache + DB fallback
        post_ids = [item.post_id for item in page_items]
        posts = await self._get_posts_with_cache(post_ids)

        # Sort by created_at descending (reverse chronological)
        posts.sort(key=lambda p: p.created_at, reverse=True)
        return posts

    async def _build_feed_from_db(self, user_id: str) -> list:
        """Build feed from database when cache is empty."""
        from app.models import FeedItem

        # Get friends
        friend_ids = await self.db.get_friends(user_id)
        all_friends = friend_ids + [user_id]  # Include own posts

        # Get recent posts from all friends
        all_posts = []
        for fid in all_friends:
            posts = await self.db.get_user_posts(fid, limit=10)
            all_posts.extend(posts)

        # Sort by time descending
        all_posts.sort(key=lambda p: p.created_at, reverse=True)

        # Build feed items and cache them
        feed_items = []
        for post in all_posts[:self.config.max_feed_length]:
            item = FeedItem(post_id=post.post_id, user_id=post.user_id, created_at=post.created_at)
            feed_items.append(item)
            self.cache.set_post(post)  # Populate content cache

        # Store in feed cache
        if feed_items:
            self.cache.feed_cache.set(user_id, feed_items)

        return feed_items

    async def _get_posts_with_cache(self, post_ids: list[str]) -> list[Post]:
        """Get posts using content cache with DB fallback."""
        posts = []
        missing_ids = []

        for pid in post_ids:
            cached = self.cache.get_post(pid)
            if cached:
                posts.append(cached)
            else:
                missing_ids.append(pid)

        # Fetch missing from DB
        if missing_ids:
            db_posts = await self.db.get_posts_batch(missing_ids)
            self.cache.set_posts(db_posts)  # Populate cache
            posts.extend(db_posts)

        return posts

    # --- Actions ---

    async def like_post(self, user_id: str, post_id: str) -> Action:
        """Like a post."""
        action = Action(
            action_id=str(uuid.uuid4()),
            user_id=user_id,
            post_id=post_id,
            action_type=ActionType.LIKE,
            created_at=time.time(),
        )
        await self.db.add_action(action)

        # Update counter cache
        self.cache.increment_counter(f"likes:{post_id}")

        # Invalidate action cache
        self.cache.action_cache.delete(post_id)

        return action

    async def reply_to_post(self, user_id: str, post_id: str, content: str) -> Action:
        """Reply to a post."""
        action = Action(
            action_id=str(uuid.uuid4()),
            user_id=user_id,
            post_id=post_id,
            action_type=ActionType.REPLY,
            content=content,
            created_at=time.time(),
        )
        await self.db.add_action(action)
        self.cache.increment_counter(f"replies:{post_id}")
        self.cache.action_cache.delete(post_id)
        return action

    async def share_post(self, user_id: str, post_id: str) -> Action:
        """Share a post."""
        action = Action(
            action_id=str(uuid.uuid4()),
            user_id=user_id,
            post_id=post_id,
            action_type=ActionType.SHARE,
            created_at=time.time(),
        )
        await self.db.add_action(action)
        self.cache.increment_counter(f"shares:{post_id}")
        return action

    async def get_post_actions(self, post_id: str, action_type: str = None) -> list:
        """Get actions for a post (with cache)."""
        cache_key = f"{post_id}:{action_type}" if action_type else post_id
        cached = self.cache.get_actions(cache_key)
        if cached is not None:
            return cached

        actions = await self.db.get_post_actions(post_id, action_type)
        self.cache.set_actions(cache_key, actions)
        return actions

    # --- User Management ---

    async def create_user(self, user_id: str, username: str, display_name: str) -> User:
        user = User(user_id=user_id, username=username, display_name=display_name)
        await self.db.create_user(user)
        return user

    async def add_friend(self, user_id: str, friend_id: str):
        await self.db.add_friend(user_id, friend_id)
        # Invalidate graph cache
        self.cache.graph_cache.delete(user_id)
        self.cache.graph_cache.delete(friend_id)

    async def get_user(self, user_id: str) -> Optional[User]:
        return await self.db.get_user(user_id)

    @property
    def stats(self) -> dict:
        return {
            "cache": self.cache.stats,
            "fanout": self.fanout.stats,
        }
