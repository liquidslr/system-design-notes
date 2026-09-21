"""
Third-party service provider interfaces.

Design doc:
- iOS Push: Apple Push Notification Service (APNS)
- Android Push: Firebase Cloud Messaging (FCM)
- SMS: Twilio / Nexmo
- Email: SendGrid / Mailchimp

All providers implement a common interface and have mock implementations for demo.
"""
import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationProvider(ABC):
    """Base interface for all notification providers."""

    @property
    @abstractmethod
    def channel_name(self) -> str:
        ...

    @abstractmethod
    async def send(self, recipient: str, title: Optional[str], body: str, metadata: dict = None) -> bool:
        """Send a notification. Returns True on success."""
        ...


class APNSProvider(NotificationProvider):
    """Apple Push Notification Service (APNS) provider."""

    def __init__(self, key: str = "", secret: str = ""):
        self.key = key
        self.secret = secret

    @property
    def channel_name(self) -> str:
        return "push_ios"

    async def send(self, recipient: str, title: Optional[str], body: str, metadata: dict = None) -> bool:
        """Send push notification via APNS (mock)."""
        # In production: use aioapns or similar library
        await asyncio.sleep(0.1)  # Simulate network latency
        success = random.random() > 0.05  # 95% success rate
        if success:
            logger.info(f"[APNS] Sent push to device {recipient[:16]}... | {title}")
        else:
            logger.warning(f"[APNS] Failed to send push to device {recipient[:16]}...")
        return success


class FCMProvider(NotificationProvider):
    """Firebase Cloud Messaging (FCM) provider."""

    def __init__(self, server_key: str = ""):
        self.server_key = server_key

    @property
    def channel_name(self) -> str:
        return "push_android"

    async def send(self, recipient: str, title: Optional[str], body: str, metadata: dict = None) -> bool:
        """Send push notification via FCM (mock)."""
        await asyncio.sleep(0.1)
        success = random.random() > 0.05
        if success:
            logger.info(f"[FCM] Sent push to device {recipient[:16]}... | {title}")
        else:
            logger.warning(f"[FCM] Failed to send push to device {recipient[:16]}...")
        return success


class SMSProvider(NotificationProvider):
    """SMS provider (Twilio/Nexmo mock)."""

    def __init__(self, sid: str = "", token: str = "", from_number: str = ""):
        self.sid = sid
        self.token = token
        self.from_number = from_number

    @property
    def channel_name(self) -> str:
        return "sms"

    async def send(self, recipient: str, title: Optional[str], body: str, metadata: dict = None) -> bool:
        """Send SMS (mock)."""
        await asyncio.sleep(0.15)
        success = random.random() > 0.03  # 97% success rate
        if success:
            logger.info(f"[SMS] Sent to {recipient}: {body[:50]}...")
        else:
            logger.warning(f"[SMS] Failed to send to {recipient}")
        return success


class EmailProvider(NotificationProvider):
    """Email provider (SendGrid mock)."""

    def __init__(self, api_key: str = "", from_email: str = "noreply@example.com"):
        self.api_key = api_key
        self.from_email = from_email

    @property
    def channel_name(self) -> str:
        return "email"

    async def send(self, recipient: str, title: Optional[str], body: str, metadata: dict = None) -> bool:
        """Send email (mock)."""
        await asyncio.sleep(0.2)
        success = random.random() > 0.02  # 98% success rate
        if success:
            logger.info(f"[EMAIL] Sent to {recipient}: {title}")
        else:
            logger.warning(f"[EMAIL] Failed to send to {recipient}")
        return success


class ProviderRegistry:
    """Registry of notification providers."""

    def __init__(self):
        self._providers: dict[str, NotificationProvider] = {}

    def register(self, provider: NotificationProvider):
        self._providers[provider.channel_name] = provider

    def get(self, channel: str) -> Optional[NotificationProvider]:
        return self._providers.get(channel)

    def create_default(self, config=None) -> "ProviderRegistry":
        """Create registry with mock providers."""
        from app.config import NotificationConfig
        cfg = config or NotificationConfig()

        self.register(APNSProvider(cfg.apns_key, cfg.apns_secret))
        self.register(FCMProvider(cfg.fcm_server_key))
        self.register(SMSProvider(cfg.twilio_sid, cfg.twilio_token, cfg.twilio_from_number))
        self.register(EmailProvider(cfg.sendgrid_api_key, cfg.sendgrid_from_email))
        return self

    @property
    def channels(self) -> list[str]:
        return list(self._providers.keys())
