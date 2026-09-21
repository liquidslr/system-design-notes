"""
Notification Server — FastAPI application.

Design doc:
- "Notification Server: Provide APIs for services to send notifications."
- "Carry out basic validations to verify emails, phone numbers."
- "Query the database or cache to fetch data needed to render a notification."
- Security: "Use AppKey and AppSecret to authenticate and secure APIs."
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from app.config import NotificationConfig
from app.database import Database
from app.models import (
    DeviceToken, NotificationRequest, NotificationSettings,
    NotificationType, UserInfo,
)
from app.providers.providers import ProviderRegistry
from app.queue.message_queue import MessageQueue
from app.service import NotificationService
from app.templates import TemplateEngine
from app.workers import WorkerPool

logger = logging.getLogger(__name__)

# --- Global instances (initialized in lifespan) ---
config = NotificationConfig()
db = Database(config)
queue = MessageQueue()
template_engine = TemplateEngine()
providers = ProviderRegistry().create_default(config)
service = NotificationService(config, db, queue, template_engine)
workers = WorkerPool(config, db, queue, providers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and clean up resources."""
    await db.initialize()
    await workers.start()
    logger.info("Notification system started")
    yield
    await workers.stop()
    await db.close()
    logger.info("Notification system stopped")


app = FastAPI(
    title="Notification System",
    description="Scalable notification system with Push, SMS, and Email support",
    version="1.0.0",
    lifespan=lifespan,
)


# --- Pydantic request/response models ---

class SendNotificationRequest(BaseModel):
    user_id: str
    event_type: str = "system"
    channel: str = "email"  # push_ios, push_android, sms, email
    template_id: Optional[str] = None
    template_data: dict = Field(default_factory=dict)
    title: Optional[str] = None
    body: Optional[str] = None
    priority: str = "normal"
    event_id: Optional[str] = None


class RegisterUserRequest(BaseModel):
    user_id: str
    email: Optional[str] = None
    phone: Optional[str] = None


class RegisterDeviceRequest(BaseModel):
    user_id: str
    device_token: str
    platform: str  # ios or android


class UpdateSettingsRequest(BaseModel):
    user_id: str
    push_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None


# --- API Endpoints ---

@app.post("/api/notifications/send")
async def send_notification(request: SendNotificationRequest):
    """
    Send a notification.
    Design doc: "Trigger services call APIs to send notifications."
    """
    try:
        channel = NotificationType(request.channel)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {request.channel}. Must be one of: push_ios, push_android, sms, email")

    notif_request = NotificationRequest(
        user_id=request.user_id,
        event_type=request.event_type,
        channel=channel,
        template_id=request.template_id,
        template_data=request.template_data,
        title=request.title,
        body=request.body,
        priority=request.priority,
        event_id=request.event_id,
    )

    result = await service.process_request(notif_request)
    return result


@app.post("/api/users/register")
async def register_user(request: RegisterUserRequest):
    """Register a user with contact information."""
    user = UserInfo(
        user_id=request.user_id,
        email=request.email,
        phone=request.phone,
        created_at=time.time(),
    )
    await db.upsert_user(user)
    return {"status": "ok", "user_id": request.user_id}


@app.post("/api/devices/register")
async def register_device(request: RegisterDeviceRequest):
    """
    Register a device token for push notifications.
    Design doc: "Collect device tokens during app installation."
    """
    if request.platform not in ("ios", "android"):
        raise HTTPException(status_code=400, detail="Platform must be 'ios' or 'android'")

    token = DeviceToken(
        user_id=request.user_id,
        device_token=request.device_token,
        platform=request.platform,
    )
    await db.register_device(token)
    return {"status": "ok"}


@app.put("/api/settings")
async def update_settings(request: UpdateSettingsRequest):
    """
    Update user notification preferences.
    Design doc: "Users can opt-in or opt-out for specific channels."
    """
    settings = await db.get_settings(request.user_id)
    if request.push_enabled is not None:
        settings.push_enabled = request.push_enabled
    if request.sms_enabled is not None:
        settings.sms_enabled = request.sms_enabled
    if request.email_enabled is not None:
        settings.email_enabled = request.email_enabled
    settings.updated_at = time.time()

    await db.upsert_settings(settings)
    return {"status": "ok", "settings": {
        "push_enabled": settings.push_enabled,
        "sms_enabled": settings.sms_enabled,
        "email_enabled": settings.email_enabled,
    }}


@app.get("/api/settings/{user_id}")
async def get_settings(user_id: str):
    """Get user notification settings."""
    settings = await db.get_settings(user_id)
    return {
        "user_id": user_id,
        "push_enabled": settings.push_enabled,
        "sms_enabled": settings.sms_enabled,
        "email_enabled": settings.email_enabled,
    }


@app.get("/api/logs")
async def get_logs(user_id: Optional[str] = None, limit: int = 50):
    """Get notification logs."""
    logs = await db.get_logs(user_id=user_id, limit=limit)
    return {"logs": logs, "count": len(logs)}


@app.get("/api/stats")
async def get_stats():
    """Get system statistics."""
    db_stats = await db.get_stats()
    return {
        "service": service.stats,
        "workers": workers.stats,
        "queue": queue.stats,
        "database": db_stats,
        "providers": providers.channels,
        "templates": template_engine.list_templates(),
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notification-system"}
