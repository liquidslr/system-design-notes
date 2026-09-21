import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from jose import jwt

from app.config import settings
from app.connection_manager import manager
from app.message_handler import handle_send_message, handle_sync, recover_messages_from_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Recover messages from PostgreSQL to Redis
    await recover_messages_from_db()
    # Start Pub/Sub listener
    task = asyncio.create_task(manager.listen_pubsub())
    yield
    task.cancel()


app = FastAPI(title="Chat Server", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """
    WebSocket endpoint. Client connects with ws://host:8001/ws?token=<jwt_token>
    """
    # Decode JWT to get user_id
    try:
        payload = jwt.decode(token, settings.SECRET_KEY if hasattr(settings, 'SECRET_KEY') else "change-me-in-production-use-openssl-rand-hex-32", algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token")
            return
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "send_message":
                logger.info(f"User {user_id} sending message to {data['receiver_id']}, type={data.get('channel_type', 'one_to_one')}")
                message = await handle_send_message(
                    sender_id=user_id,
                    receiver_id=data["receiver_id"],
                    content=data["content"],
                    channel_type=data.get("channel_type", "one_to_one"),
                )
                # Send back to sender for confirmation
                await manager.send_personal(user_id, {
                    "type": "new_message",
                    "message": message,
                })
                logger.info(f"Message {message['message_id']} sent and confirmation delivered to {user_id}")

            elif msg_type == "sync":
                messages = await handle_sync(
                    user_id=user_id,
                    channel_id=data["channel_id"],
                    last_message_id=data.get("last_message_id", "0"),
                )
                await manager.send_personal(user_id, {
                    "type": "message_sync",
                    "messages": messages,
                })

            elif msg_type == "typing":
                channel_id = data.get("channel_id")
                if channel_id:
                    await manager.send_personal(channel_id, {
                        "type": "typing",
                        "user_id": user_id,
                    })

    except Exception as e:
        logger.exception(f"WebSocket error for user {user_id}: {e}")
        manager.disconnect(user_id)
        await manager.cleanup(user_id)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "chat-server"}
