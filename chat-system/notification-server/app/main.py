from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.notifier import notification_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    await notification_service.start()
    yield
    await notification_service.stop()


app = FastAPI(title="Notification Server", lifespan=lifespan)


@app.get("/notifications")
async def get_notifications():
    """Get recent offline notifications (for debugging/demo)."""
    return notification_service.notifications


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notification-server"}
