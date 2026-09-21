from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.heartbeat import heartbeat_checker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await heartbeat_checker.start()
    yield
    await heartbeat_checker.stop()


app = FastAPI(title="Presence Server", lifespan=lifespan)


@app.post("/heartbeat")
async def receive_heartbeat(user_id: str):
    """Receive heartbeat from a client."""
    await heartbeat_checker.update_heartbeat(user_id)
    return {"status": "ok"}


@app.get("/presence/{user_id}")
async def get_presence(user_id: str):
    """Get online status of a user."""
    r = heartbeat_checker.redis
    data = await r.hgetall(f"presence:{user_id}")
    if not data:
        return {"user_id": user_id, "status": "offline"}
    return {"user_id": user_id, "status": data.get("status", "offline")}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "presence-server"}
