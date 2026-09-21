"""
Database layer for the Notification System.

Design doc:
- Device Tokens Table: For push notifications
- User Table: For emails and phone numbers
- Notification Settings Table: Opt-in/opt-out per channel
- Notification Log Table: Persistence for retry and analytics
"""
import logging
import time
import uuid
from typing import Optional

import aiosqlite

from app.config import NotificationConfig
from app.models import (
    DeviceToken, NotificationLog, NotificationSettings, UserInfo,
)

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for notification system metadata and logs."""

    def __init__(self, config: NotificationConfig):
        self.config = config
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Create database and tables."""
        self._db = await aiosqlite.connect(self.config.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT,
                phone TEXT,
                created_at REAL
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS device_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                device_token TEXT NOT NULL,
                platform TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS notification_settings (
                user_id TEXT PRIMARY KEY,
                push_enabled INTEGER DEFAULT 1,
                sms_enabled INTEGER DEFAULT 1,
                email_enabled INTEGER DEFAULT 1,
                updated_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS notification_logs (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                recipient TEXT NOT NULL,
                title TEXT,
                body TEXT,
                status TEXT NOT NULL,
                event_type TEXT,
                created_at REAL,
                sent_at REAL,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0
            )
        """)

        # Index for deduplication lookup
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_event_id
            ON notification_logs(event_id)
        """)

        # Index for rate limiting lookup
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_user_created
            ON notification_logs(user_id, created_at)
        """)

        await self._db.commit()
        logger.info("Database initialized")

    # --- User operations ---

    async def upsert_user(self, user: UserInfo):
        await self._db.execute(
            """INSERT OR REPLACE INTO users (user_id, email, phone, created_at)
               VALUES (?, ?, ?, ?)""",
            (user.user_id, user.email, user.phone, user.created_at),
        )
        await self._db.commit()

    async def get_user(self, user_id: str) -> Optional[UserInfo]:
        async with self._db.execute(
            "SELECT user_id, email, phone, created_at FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return UserInfo(user_id=row[0], email=row[1], phone=row[2], created_at=row[3])
        return None

    # --- Device token operations ---

    async def register_device(self, token: DeviceToken):
        token_id = str(uuid.uuid4())
        await self._db.execute(
            """INSERT INTO device_tokens (id, user_id, device_token, platform, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token_id, token.user_id, token.device_token, token.platform,
             int(token.is_active), token.created_at),
        )
        await self._db.commit()

    async def get_active_device_tokens(self, user_id: str) -> list[DeviceToken]:
        tokens = []
        async with self._db.execute(
            """SELECT user_id, device_token, platform, is_active, created_at
               FROM device_tokens WHERE user_id = ? AND is_active = 1""",
            (user_id,),
        ) as cursor:
            async for row in cursor:
                tokens.append(DeviceToken(
                    user_id=row[0], device_token=row[1], platform=row[2],
                    is_active=bool(row[3]), created_at=row[4],
                ))
        return tokens

    # --- Notification settings ---

    async def upsert_settings(self, settings: NotificationSettings):
        await self._db.execute(
            """INSERT OR REPLACE INTO notification_settings
               (user_id, push_enabled, sms_enabled, email_enabled, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (settings.user_id, int(settings.push_enabled), int(settings.sms_enabled),
             int(settings.email_enabled), settings.updated_at),
        )
        await self._db.commit()

    async def get_settings(self, user_id: str) -> NotificationSettings:
        async with self._db.execute(
            "SELECT user_id, push_enabled, sms_enabled, email_enabled, updated_at FROM notification_settings WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return NotificationSettings(
                    user_id=row[0], push_enabled=bool(row[1]),
                    sms_enabled=bool(row[2]), email_enabled=bool(row[3]),
                    updated_at=row[4],
                )
        # Default: all enabled
        return NotificationSettings(user_id=user_id)

    # --- Notification log operations ---

    async def insert_log(self, log: NotificationLog):
        await self._db.execute(
            """INSERT INTO notification_logs
               (id, event_id, user_id, channel, recipient, title, body, status, event_type, created_at, sent_at, error_message, retry_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (log.id, log.event_id, log.user_id, log.channel, log.recipient,
             log.title, log.body, log.status, log.event_type, log.created_at,
             log.sent_at, log.error_message, log.retry_count),
        )
        await self._db.commit()

    async def update_log_status(self, event_id: str, status: str, error_message: str = None, sent_at: float = None):
        await self._db.execute(
            """UPDATE notification_logs SET status = ?, error_message = ?, sent_at = ?
               WHERE event_id = ?""",
            (status, error_message, sent_at, event_id),
        )
        await self._db.commit()

    async def is_duplicate_event(self, event_id: str) -> bool:
        """Check if an event ID has already been processed (deduplication)."""
        async with self._db.execute(
            "SELECT 1 FROM notification_logs WHERE event_id = ? LIMIT 1",
            (event_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def count_recent_notifications(self, user_id: str, since: float) -> int:
        """Count notifications sent to a user since a timestamp (for rate limiting)."""
        async with self._db.execute(
            "SELECT COUNT(*) FROM notification_logs WHERE user_id = ? AND created_at >= ?",
            (user_id, since),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_logs(self, user_id: str = None, limit: int = 50) -> list[dict]:
        """Get notification logs, optionally filtered by user."""
        if user_id:
            query = "SELECT * FROM notification_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
            params = (user_id, limit)
        else:
            query = "SELECT * FROM notification_logs ORDER BY created_at DESC LIMIT ?"
            params = (limit,)

        logs = []
        async with self._db.execute(query, params) as cursor:
            columns = [desc[0] for desc in cursor.description]
            async for row in cursor:
                logs.append(dict(zip(columns, row)))
        return logs

    async def get_stats(self) -> dict:
        """Get overall notification statistics."""
        stats = {}
        for status in ["sent", "failed", "pending", "rate_limited", "duplicate", "opted_out"]:
            async with self._db.execute(
                "SELECT COUNT(*) FROM notification_logs WHERE status = ?", (status,)
            ) as cursor:
                row = await cursor.fetchone()
                stats[status] = row[0] if row else 0

        async with self._db.execute("SELECT COUNT(*) FROM notification_logs") as cursor:
            row = await cursor.fetchone()
            stats["total"] = row[0] if row else 0

        async with self._db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            stats["total_users"] = row[0] if row else 0

        return stats

    async def close(self):
        if self._db:
            await self._db.close()
