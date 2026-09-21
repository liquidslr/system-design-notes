"""
Core data models for the Notification System.

Design doc:
- Notification Types: Push (iOS/Android), SMS, Email
- Contact Info: device tokens, phone numbers, emails
- Event tracking: open rate, click rate, engagement
"""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class NotificationType(str, Enum):
    PUSH_IOS = "push_ios"
    PUSH_ANDROID = "push_android"
    SMS = "sms"
    EMAIL = "email"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    RETRYING = "retrying"
    RATE_LIMITED = "rate_limited"
    DUPLICATE = "duplicate"
    OPTED_OUT = "opted_out"


class EventType(str, Enum):
    """Notification event types that can trigger notifications."""
    BILLING_REMINDER = "billing_reminder"
    SHIPPING_UPDATE = "shipping_update"
    PRICE_DROP = "price_drop"
    SECURITY_ALERT = "security_alert"
    PROMOTION = "promotion"
    SYSTEM = "system"
    CUSTOM = "custom"


@dataclass
class NotificationRequest:
    """Incoming request to send a notification."""
    user_id: str
    event_type: str
    channel: NotificationType
    template_id: Optional[str] = None
    template_data: dict = field(default_factory=dict)
    title: Optional[str] = None
    body: Optional[str] = None
    priority: str = "normal"  # low, normal, high, urgent
    event_id: Optional[str] = None  # For deduplication

    def __post_init__(self):
        if self.event_id is None:
            self.event_id = str(uuid.uuid4())


@dataclass
class NotificationEvent:
    """A notification event in the queue."""
    event_id: str
    user_id: str
    channel: NotificationType
    recipient: str  # device token, phone number, or email
    title: Optional[str]
    body: str
    event_type: str
    priority: str
    created_at: float
    retry_count: int = 0
    status: NotificationStatus = NotificationStatus.PENDING
    metadata: dict = field(default_factory=dict)


@dataclass
class NotificationLog:
    """Persisted notification log for tracking and analytics."""
    id: str
    event_id: str
    user_id: str
    channel: str
    recipient: str
    title: Optional[str]
    body: str
    status: str
    event_type: str
    created_at: float
    sent_at: Optional[float] = None
    error_message: Optional[str] = None
    retry_count: int = 0


@dataclass
class UserInfo:
    """User contact information."""
    user_id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    created_at: float = field(default_factory=time.time)


@dataclass
class DeviceToken:
    """Device token for push notifications."""
    user_id: str
    device_token: str
    platform: str  # ios or android
    is_active: bool = True
    created_at: float = field(default_factory=time.time)


@dataclass
class NotificationSettings:
    """User notification preferences (opt-in/opt-out)."""
    user_id: str
    push_enabled: bool = True
    sms_enabled: bool = True
    email_enabled: bool = True
    updated_at: float = field(default_factory=time.time)
