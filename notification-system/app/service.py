"""
Notification Service — Core business logic.

Design doc flow:
1. Trigger services call APIs to send notifications.
2. Notification servers validate requests and fetch metadata from caches or databases.
3. Notification events are sent to message queues.
4. Workers process events and interact with third-party services.

Features:
- Deduplication (event ID check)
- Rate limiting (per user per hour/day)
- Opt-out check
- Template rendering
"""
import logging
import time
import uuid
from typing import Optional

from app.config import NotificationConfig
from app.database import Database
from app.models import (
    NotificationEvent, NotificationLog, NotificationRequest,
    NotificationStatus, NotificationType,
)
from app.queue.message_queue import MessageQueue
from app.templates import TemplateEngine

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Core notification processing service.
    Handles validation, dedup, rate limiting, and queueing.
    """

    def __init__(
        self,
        config: NotificationConfig,
        db: Database,
        queue: MessageQueue,
        template_engine: TemplateEngine,
    ):
        self.config = config
        self.db = db
        self.queue = queue
        self.template_engine = template_engine

        # Stats
        self._total_received = 0
        self._total_rejected = 0
        self._total_queued = 0

    async def process_request(self, request: NotificationRequest) -> dict:
        """
        Process an incoming notification request.
        Returns status dict.
        """
        self._total_received += 1

        # Step 1: Validate request
        validation_error = self._validate_request(request)
        if validation_error:
            self._total_rejected += 1
            return {"status": "rejected", "reason": validation_error}

        # Step 2: Deduplication — check if event was already processed
        if await self.db.is_duplicate_event(request.event_id):
            self._total_rejected += 1
            logger.info(f"Duplicate event detected: {request.event_id}")
            await self._log_notification(request, "", "", NotificationStatus.DUPLICATE)
            return {"status": "duplicate", "event_id": request.event_id}

        # Step 3: Check opt-out settings
        settings = await self.db.get_settings(request.user_id)
        channel_enabled = self._is_channel_enabled(settings, request.channel)
        if not channel_enabled:
            self._total_rejected += 1
            logger.info(f"User {request.user_id} opted out of {request.channel.value}")
            await self._log_notification(request, "", "", NotificationStatus.OPTED_OUT)
            return {"status": "opted_out", "channel": request.channel.value}

        # Step 4: Rate limiting
        rate_limited = await self._check_rate_limit(request.user_id)
        if rate_limited:
            self._total_rejected += 1
            logger.info(f"Rate limited: user {request.user_id}")
            await self._log_notification(request, "", "", NotificationStatus.RATE_LIMITED)
            return {"status": "rate_limited", "user_id": request.user_id}

        # Step 5: Resolve recipient
        recipient = await self._resolve_recipient(request.user_id, request.channel)
        if not recipient:
            self._total_rejected += 1
            return {"status": "rejected", "reason": f"No recipient found for {request.channel.value}"}

        # Step 6: Render template
        title, body = self._render_content(request)
        if not body:
            self._total_rejected += 1
            return {"status": "rejected", "reason": "Empty notification body"}

        # Step 7: Create event and enqueue
        event = NotificationEvent(
            event_id=request.event_id,
            user_id=request.user_id,
            channel=request.channel,
            recipient=recipient,
            title=title,
            body=body,
            event_type=request.event_type,
            priority=request.priority,
            created_at=time.time(),
        )

        success = await self.queue.enqueue(event)
        if success:
            self._total_queued += 1
            await self._log_notification(request, recipient, body, NotificationStatus.QUEUED, title=title)
            return {"status": "queued", "event_id": event.event_id}
        else:
            return {"status": "error", "reason": "Queue full"}

    def _validate_request(self, request: NotificationRequest) -> Optional[str]:
        """Basic validation."""
        if not request.user_id:
            return "user_id is required"
        if not request.event_type:
            return "event_type is required"
        if not request.channel:
            return "channel is required"
        if not request.body and not request.template_id:
            return "Either body or template_id is required"
        return None

    def _is_channel_enabled(self, settings, channel: NotificationType) -> bool:
        if channel in (NotificationType.PUSH_IOS, NotificationType.PUSH_ANDROID):
            return settings.push_enabled
        elif channel == NotificationType.SMS:
            return settings.sms_enabled
        elif channel == NotificationType.EMAIL:
            return settings.email_enabled
        return True

    async def _check_rate_limit(self, user_id: str) -> bool:
        """Check if user has exceeded rate limits. Returns True if rate limited."""
        now = time.time()
        one_hour_ago = now - 3600
        one_day_ago = now - 86400

        hour_count = await self.db.count_recent_notifications(user_id, one_hour_ago)
        if hour_count >= self.config.rate_limit_per_user_per_hour:
            return True

        day_count = await self.db.count_recent_notifications(user_id, one_day_ago)
        if day_count >= self.config.rate_limit_per_user_per_day:
            return True

        return False

    async def _resolve_recipient(self, user_id: str, channel: NotificationType) -> Optional[str]:
        """Resolve the recipient address based on channel."""
        if channel == NotificationType.PUSH_IOS:
            tokens = await self.db.get_active_device_tokens(user_id)
            ios_tokens = [t for t in tokens if t.platform == "ios"]
            return ios_tokens[0].device_token if ios_tokens else None

        elif channel == NotificationType.PUSH_ANDROID:
            tokens = await self.db.get_active_device_tokens(user_id)
            android_tokens = [t for t in tokens if t.platform == "android"]
            return android_tokens[0].device_token if android_tokens else None

        elif channel == NotificationType.SMS:
            user = await self.db.get_user(user_id)
            return user.phone if user else None

        elif channel == NotificationType.EMAIL:
            user = await self.db.get_user(user_id)
            return user.email if user else None

        return None

    def _render_content(self, request: NotificationRequest) -> tuple[Optional[str], str]:
        """Render notification content from template or raw data."""
        if request.template_id:
            return self.template_engine.render(request.template_id, request.template_data)
        return request.title, request.body or ""

    async def _log_notification(
        self,
        request: NotificationRequest,
        recipient: str,
        body: str,
        status: NotificationStatus,
        title: str = None,
    ):
        """Persist notification log."""
        log = NotificationLog(
            id=str(uuid.uuid4()),
            event_id=request.event_id,
            user_id=request.user_id,
            channel=request.channel.value,
            recipient=recipient,
            title=title or request.title,
            body=body or request.body or "",
            status=status.value,
            event_type=request.event_type,
            created_at=time.time(),
        )
        await self.db.insert_log(log)

    @property
    def stats(self) -> dict:
        return {
            "total_received": self._total_received,
            "total_rejected": self._total_rejected,
            "total_queued": self._total_queued,
            "queue": self.queue.stats,
        }
