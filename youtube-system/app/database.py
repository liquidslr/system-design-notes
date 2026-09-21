"""Async SQLite storage for video metadata.

Single-writer design: only api-server touches this database. Workers
communicate state changes through Redis events consumed by
completion_consumer.py.
"""
import logging
import os
import time
import uuid

import aiosqlite

from app.config import config

logger = logging.getLogger(__name__)


async def init_db() -> None:
    os.makedirs(os.path.dirname(config.db_path), exist_ok=True)
    async with aiosqlite.connect(config.db_path) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                original_path TEXT,
                duration_sec REAL,
                width INTEGER,
                height INTEGER,
                error_msg TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS renditions (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL REFERENCES videos(id),
                resolution TEXT NOT NULL,
                playlist_path TEXT,
                bitrate_kbps INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(video_id, resolution)
            );
            CREATE INDEX IF NOT EXISTS idx_renditions_video ON renditions(video_id);
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS comments (
                id            TEXT PRIMARY KEY,
                video_id      TEXT NOT NULL REFERENCES videos(id),
                author_id     TEXT NOT NULL REFERENCES users(id),
                parent_id     TEXT REFERENCES comments(id),
                root_id       TEXT REFERENCES comments(id),
                body          TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'active',
                like_count    INTEGER NOT NULL DEFAULT 0,
                dislike_count INTEGER NOT NULL DEFAULT 0,
                score         INTEGER NOT NULL DEFAULT 0,
                created_at    REAL NOT NULL,
                updated_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comments_thread
                ON comments(root_id, status);
            CREATE INDEX IF NOT EXISTS idx_comments_sort
                ON comments(video_id, status, score, created_at);
            CREATE TABLE IF NOT EXISTS comment_votes (
                user_id    TEXT NOT NULL REFERENCES users(id),
                comment_id TEXT NOT NULL REFERENCES comments(id),
                value      INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (user_id, comment_id)
            );
            CREATE INDEX IF NOT EXISTS idx_votes_comment
                ON comment_votes(comment_id);
        """)
        # videos.uploader_id is nullable: rows created before the user system
        # stay anonymous. SQLite has no ADD COLUMN IF NOT EXISTS, so probe first.
        cursor = await db.execute("PRAGMA table_info(videos)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "uploader_id" not in columns:
            await db.execute(
                "ALTER TABLE videos ADD COLUMN uploader_id TEXT REFERENCES users(id)")
            logger.info("Migrated videos: added uploader_id column")
        # moderation columns: existing rows get 'approved' (stay visible).
        if "moderation_status" not in columns:
            await db.execute(
                "ALTER TABLE videos ADD COLUMN moderation_status "
                "TEXT NOT NULL DEFAULT 'approved'")
            logger.info("Migrated videos: added moderation_status column")
        if "rejection_reason" not in columns:
            await db.execute(
                "ALTER TABLE videos ADD COLUMN rejection_reason TEXT")
            logger.info("Migrated videos: added rejection_reason column")
        await db.execute(
            """CREATE INDEX IF NOT EXISTS idx_videos_public
               ON videos(status, moderation_status, created_at)""")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_uploader ON videos(uploader_id)")
        await db.commit()
    logger.info("Database initialized")


_VIDEO_SELECT = """
    SELECT v.*, u.username AS uploader_username
    FROM videos v LEFT JOIN users u ON v.uploader_id = u.id
"""


async def insert_video(video_id: str, title: str, description: str,
                       original_path: str, uploader_id: str | None = None) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO videos (id, title, description, status, original_path,
                                   uploader_id, moderation_status, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, 'pending_review', ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 original_path=excluded.original_path,
                 uploader_id=excluded.uploader_id, status='pending',
                 moderation_status='pending_review',
                 error_msg=NULL, updated_at=excluded.updated_at""",
            (video_id, title, description, original_path, uploader_id, now, now),
        )
        await db.commit()


async def get_video(video_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT + " WHERE v.id = ?", (video_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_videos() -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(_VIDEO_SELECT + " ORDER BY v.created_at DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def list_videos_by_uploader(uploader_id: str) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT + " WHERE v.uploader_id = ? ORDER BY v.created_at DESC",
            (uploader_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def set_video_status(video_id: str, status: str,
                           error_msg: str | None = None) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE videos SET status = ?, error_msg = ?, updated_at = ? WHERE id = ?",
            (status, error_msg, time.time(), video_id),
        )
        await db.commit()


async def upsert_video_info(video_id: str, duration_sec: float | None,
                            width: int | None, height: int | None) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """UPDATE videos
               SET duration_sec = ?, width = ?, height = ?, updated_at = ?
               WHERE id = ?""",
            (duration_sec, width, height, time.time(), video_id),
        )
        await db.commit()


async def replace_renditions(video_id: str, renditions: list[dict]) -> None:
    """Replace rendition rows with the set announced by the worker."""
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute("DELETE FROM renditions WHERE video_id = ?", (video_id,))
        for r in renditions:
            await db.execute(
                """INSERT INTO renditions (id, video_id, resolution, bitrate_kbps, status)
                   VALUES (?, ?, ?, ?, 'processing')""",
                (uuid.uuid4().hex, video_id, r["resolution"], r["bitrate_kbps"]),
            )
        await db.commit()


async def set_rendition_done(video_id: str, resolution: str,
                             playlist_path: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """UPDATE renditions SET status = 'done', playlist_path = ?
               WHERE video_id = ? AND resolution = ?""",
            (playlist_path, video_id, resolution),
        )
        await db.commit()


async def set_renditions_failed(video_id: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE renditions SET status = 'failed' WHERE video_id = ?", (video_id,)
        )
        await db.commit()


async def get_renditions(video_id: str) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT resolution, playlist_path, bitrate_kbps, status
               FROM renditions WHERE video_id = ?""",
            (video_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_by_status() -> dict[str, int]:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute("SELECT status, COUNT(*) FROM videos GROUP BY status")
        return {row[0]: row[1] for row in await cursor.fetchall()}


async def insert_user(user_id: str, username: str, email: str,
                      password_hash: str, role: str) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO users (id, username, email, password_hash, role,
                                  status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
            (user_id, username, email, password_hash, role, now, now),
        )
        await db.commit()


async def get_user_by_email(email: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_username(username: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_users(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_users() -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0]


async def set_user_role(user_id: str, role: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
            (role, time.time(), user_id),
        )
        await db.commit()


async def set_user_status(user_id: str, status: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), user_id),
        )
        await db.commit()


_COMMENT_SELECT = """
    SELECT c.*, u.username AS author_username
    FROM comments c LEFT JOIN users u ON c.author_id = u.id
"""


async def insert_comment(comment_id: str, video_id: str, author_id: str,
                         body: str, parent_id: str | None,
                         root_id: str | None) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO comments (id, video_id, author_id, parent_id, root_id,
                                      body, status, like_count, dislike_count,
                                      score, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', 0, 0, 0, ?, ?)""",
            (comment_id, video_id, author_id, parent_id, root_id, body, now, now),
        )
        await db.commit()


async def get_comment(comment_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _COMMENT_SELECT + " WHERE c.id = ?", (comment_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_top_comments(video_id: str, sort: str, limit: int,
                            offset: int) -> list[dict]:
    order = ("c.score DESC, c.created_at DESC" if sort == "top"
             else "c.created_at DESC")
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _COMMENT_SELECT
            + " WHERE c.video_id = ? AND c.parent_id IS NULL"
            + f" ORDER BY {order} LIMIT ? OFFSET ?",
            (video_id, limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_top_comments(video_id: str) -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM comments WHERE video_id = ? AND parent_id IS NULL",
            (video_id,))
        return (await cursor.fetchone())[0]


async def list_replies(root_id: str, limit: int, offset: int) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _COMMENT_SELECT
            + " WHERE c.root_id = ? ORDER BY c.created_at ASC LIMIT ? OFFSET ?",
            (root_id, limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_replies(root_id: str) -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM comments WHERE root_id = ? AND status = 'active'",
            (root_id,))
        return (await cursor.fetchone())[0]


async def reply_counts(root_ids: list[str]) -> dict[str, int]:
    if not root_ids:
        return {}
    placeholders = ",".join("?" * len(root_ids))
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""SELECT root_id, COUNT(*) AS n FROM comments
                WHERE root_id IN ({placeholders}) AND status = 'active'
                GROUP BY root_id""",
            tuple(root_ids),
        )
        return {r["root_id"]: r["n"] for r in await cursor.fetchall()}


async def soft_delete_comment(comment_id: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE comments SET status='deleted', body='', updated_at=? "
            "WHERE id = ?",
            (time.time(), comment_id),
        )
        await db.commit()


async def viewer_votes(user_id: str, comment_ids: list[str]) -> dict[str, int]:
    if not comment_ids:
        return {}
    placeholders = ",".join("?" * len(comment_ids))
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""SELECT comment_id, value FROM comment_votes
                WHERE user_id = ? AND comment_id IN ({placeholders})""",
            (user_id, *comment_ids),
        )
        return {r["comment_id"]: r["value"] for r in await cursor.fetchall()}


async def apply_vote(user_id: str, comment_id: str, value: int) -> dict:
    """Set the viewer's vote to value (+1/-1/0) and refresh denormalized counts.

    Runs entirely in one connection (single writer => no cross-process race).
    Returns {like_count, dislike_count, score}.
    """
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        cur = await db.execute(
            "SELECT value FROM comment_votes WHERE user_id = ? AND comment_id = ?",
            (user_id, comment_id),
        )
        row = await cur.fetchone()
        old = row[0] if row else None
        if old != value:
            like_delta = dislike_delta = 0
            if value == 1:
                like_delta += 1
            elif value == -1:
                dislike_delta += 1
            if old == 1:
                like_delta -= 1
            elif old == -1:
                dislike_delta -= 1

            if value == 0:
                await db.execute(
                    "DELETE FROM comment_votes WHERE user_id = ? AND comment_id = ?",
                    (user_id, comment_id),
                )
            elif old is None:
                await db.execute(
                    """INSERT INTO comment_votes
                       (user_id, comment_id, value, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, comment_id, value, now, now),
                )
            else:
                await db.execute(
                    """UPDATE comment_votes SET value = ?, updated_at = ?
                       WHERE user_id = ? AND comment_id = ?""",
                    (value, now, user_id, comment_id),
                )
            await db.execute(
                """UPDATE comments
                   SET like_count = like_count + ?,
                       dislike_count = dislike_count + ?,
                       score = (like_count + ?) - (dislike_count + ?),
                       updated_at = ?
                   WHERE id = ?""",
                (like_delta, dislike_delta, like_delta, dislike_delta, now,
                 comment_id),
            )
        cur = await db.execute(
            "SELECT like_count, dislike_count, score FROM comments WHERE id = ?",
            (comment_id,),
        )
        r = await cur.fetchone()
        await db.commit()
        return {"like_count": r[0], "dislike_count": r[1], "score": r[2]}


# ---- moderation ----


async def set_moderation(video_id: str, status: str,
                         reason: str | None) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE videos SET moderation_status=?, rejection_reason=?, "
            "updated_at=? WHERE id=?",
            (status, reason, time.time(), video_id),
        )
        await db.commit()


async def resubmit_video(video_id: str, title: str, description: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE videos SET title=?, description=?, "
            "moderation_status='pending_review', rejection_reason=NULL, "
            "updated_at=? WHERE id=?",
            (title, description, time.time(), video_id),
        )
        await db.commit()


async def list_videos_public(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT
            + " WHERE v.status='ready' AND v.moderation_status='approved'"
            + " ORDER BY v.created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_videos_public() -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM videos "
            "WHERE status='ready' AND moderation_status='approved'")
        return (await cursor.fetchone())[0]


async def list_moderation_queue(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT
            + " WHERE v.status='ready' AND v.moderation_status='pending_review'"
            + " ORDER BY v.created_at ASC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_moderation_queue() -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM videos "
            "WHERE status='ready' AND moderation_status='pending_review'")
        return (await cursor.fetchone())[0]
