"""
Database layer for the News Feed System.

Design doc:
- Store posts, users, friendships, actions
- Support horizontal scaling and sharding (demo uses SQLite)
- Read replicas for high-traffic queries
"""
import logging
import time
import uuid
from typing import Optional

import aiosqlite

from app.config import FeedConfig
from app.models import User, Post, PostType, Friendship, Action, ActionType

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for news feed system."""

    def __init__(self, config: FeedConfig):
        self.config = config
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        self._db = await aiosqlite.connect(self.config.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                created_at REAL,
                follower_count INTEGER DEFAULT 0,
                following_count INTEGER DEFAULT 0
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                post_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                post_type TEXT DEFAULT 'text',
                media_urls TEXT DEFAULT '[]',
                created_at REAL,
                like_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                share_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS friendships (
                user_id TEXT NOT NULL,
                friend_id TEXT NOT NULL,
                created_at REAL,
                PRIMARY KEY (user_id, friend_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (friend_id) REFERENCES users(user_id)
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                action_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                post_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                content TEXT,
                created_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (post_id) REFERENCES posts(post_id)
            )
        """)

        # Indexes
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id, created_at DESC)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_friendships_user ON friendships(user_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_friendships_friend ON friendships(friend_id)")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_actions_post ON actions(post_id, action_type)")

        await self._db.commit()
        logger.info("Database initialized")

    # --- Users ---
    async def create_user(self, user: User):
        await self._db.execute(
            "INSERT OR REPLACE INTO users (user_id, username, display_name, created_at) VALUES (?, ?, ?, ?)",
            (user.user_id, user.username, user.display_name, user.created_at),
        )
        await self._db.commit()

    async def get_user(self, user_id: str) -> Optional[User]:
        async with self._db.execute(
            "SELECT user_id, username, display_name, created_at, follower_count, following_count FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return User(user_id=row[0], username=row[1], display_name=row[2],
                            created_at=row[3], follower_count=row[4], following_count=row[5])
        return None

    # --- Posts ---
    async def create_post(self, post: Post):
        import json
        media_json = json.dumps(post.media_urls)
        await self._db.execute(
            """INSERT INTO posts (post_id, user_id, content, post_type, media_urls, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (post.post_id, post.user_id, post.content, post.post_type.value, media_json, post.created_at),
        )
        await self._db.commit()

    async def get_post(self, post_id: str) -> Optional[Post]:
        import json
        async with self._db.execute(
            "SELECT post_id, user_id, content, post_type, media_urls, created_at, like_count, reply_count, share_count FROM posts WHERE post_id = ?",
            (post_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Post(
                    post_id=row[0], user_id=row[1], content=row[2],
                    post_type=PostType(row[3]), media_urls=json.loads(row[4]),
                    created_at=row[5], like_count=row[6], reply_count=row[7], share_count=row[8],
                )
        return None

    async def get_posts_batch(self, post_ids: list[str]) -> list[Post]:
        """Get multiple posts by IDs."""
        if not post_ids:
            return []
        import json
        placeholders = ",".join("?" * len(post_ids))
        posts = []
        async with self._db.execute(
            f"SELECT post_id, user_id, content, post_type, media_urls, created_at, like_count, reply_count, share_count FROM posts WHERE post_id IN ({placeholders})",
            post_ids,
        ) as cursor:
            async for row in cursor:
                posts.append(Post(
                    post_id=row[0], user_id=row[1], content=row[2],
                    post_type=PostType(row[3]), media_urls=json.loads(row[4]),
                    created_at=row[5], like_count=row[6], reply_count=row[7], share_count=row[8],
                ))
        return posts

    async def get_user_posts(self, user_id: str, limit: int = 20) -> list[Post]:
        import json
        posts = []
        async with self._db.execute(
            "SELECT post_id, user_id, content, post_type, media_urls, created_at, like_count, reply_count, share_count FROM posts WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ) as cursor:
            async for row in cursor:
                posts.append(Post(
                    post_id=row[0], user_id=row[1], content=row[2],
                    post_type=PostType(row[3]), media_urls=json.loads(row[4]),
                    created_at=row[5], like_count=row[6], reply_count=row[7], share_count=row[8],
                ))
        return posts

    # --- Friendships ---
    async def add_friend(self, user_id: str, friend_id: str):
        now = time.time()
        await self._db.execute(
            "INSERT OR IGNORE INTO friendships (user_id, friend_id, created_at) VALUES (?, ?, ?)",
            (user_id, friend_id, now),
        )
        await self._db.execute(
            "INSERT OR IGNORE INTO friendships (user_id, friend_id, created_at) VALUES (?, ?, ?)",
            (friend_id, user_id, now),
        )
        await self._db.commit()

    async def get_friends(self, user_id: str) -> list[str]:
        friend_ids = []
        async with self._db.execute(
            "SELECT friend_id FROM friendships WHERE user_id = ?", (user_id,)
        ) as cursor:
            async for row in cursor:
                friend_ids.append(row[0])
        return friend_ids

    async def get_friend_count(self, user_id: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM friendships WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    # --- Actions ---
    async def add_action(self, action: Action):
        await self._db.execute(
            "INSERT INTO actions (action_id, user_id, post_id, action_type, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (action.action_id, action.user_id, action.post_id, action.action_type.value, action.content, action.created_at),
        )
        # Update counter
        if action.action_type == ActionType.LIKE:
            await self._db.execute("UPDATE posts SET like_count = like_count + 1 WHERE post_id = ?", (action.post_id,))
        elif action.action_type == ActionType.REPLY:
            await self._db.execute("UPDATE posts SET reply_count = reply_count + 1 WHERE post_id = ?", (action.post_id,))
        elif action.action_type == ActionType.SHARE:
            await self._db.execute("UPDATE posts SET share_count = share_count + 1 WHERE post_id = ?", (action.post_id,))
        await self._db.commit()

    async def get_post_actions(self, post_id: str, action_type: str = None, limit: int = 50) -> list[Action]:
        actions = []
        if action_type:
            query = "SELECT action_id, user_id, post_id, action_type, content, created_at FROM actions WHERE post_id = ? AND action_type = ? ORDER BY created_at DESC LIMIT ?"
            params = (post_id, action_type, limit)
        else:
            query = "SELECT action_id, user_id, post_id, action_type, content, created_at FROM actions WHERE post_id = ? ORDER BY created_at DESC LIMIT ?"
            params = (post_id, limit)
        async with self._db.execute(query, params) as cursor:
            async for row in cursor:
                actions.append(Action(
                    action_id=row[0], user_id=row[1], post_id=row[2],
                    action_type=ActionType(row[3]), content=row[4], created_at=row[5],
                ))
        return actions

    async def get_stats(self) -> dict:
        stats = {}
        for table in ["users", "posts", "friendships", "actions"]:
            async with self._db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                row = await cursor.fetchone()
                stats[table] = row[0] if row else 0
        return stats

    async def close(self):
        if self._db:
            await self._db.close()
