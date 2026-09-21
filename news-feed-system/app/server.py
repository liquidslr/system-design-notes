"""
News Feed Server — FastAPI application.

Design doc APIs:
- POST /v1/me/feed — Publish a post
- GET /v1/me/feed — Get news feed
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import FeedConfig
from app.database import Database
from app.cache import CacheLayer
from app.fanout import FanoutService
from app.service import FeedService

logger = logging.getLogger(__name__)

config = FeedConfig()
db = Database(config)
cache = CacheLayer(config)
fanout = FanoutService(config, db, cache)
service = FeedService(config, db, cache, fanout)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.initialize()
    await fanout.start()
    logger.info("News Feed System started")
    yield
    await fanout.stop()
    await db.close()
    logger.info("News Feed System stopped")


app = FastAPI(title="News Feed System", version="1.0.0", lifespan=lifespan)


# --- Request/Response Models ---

class CreatePostRequest(BaseModel):
    user_id: str
    content: str
    post_type: str = "text"
    media_urls: list[str] = Field(default_factory=list)


class CreateUserRequest(BaseModel):
    user_id: str
    username: str
    display_name: str


class AddFriendRequest(BaseModel):
    user_id: str
    friend_id: str


class LikeRequest(BaseModel):
    user_id: str
    post_id: str


class ReplyRequest(BaseModel):
    user_id: str
    post_id: str
    content: str


class ShareRequest(BaseModel):
    user_id: str
    post_id: str


# --- Feed APIs ---

@app.post("/v1/me/feed")
async def publish_post(request: CreatePostRequest):
    """Feed Publishing API — POST /v1/me/feed"""
    user = await service.get_user(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    post = await service.create_post(
        user_id=request.user_id,
        content=request.content,
        post_type=request.post_type,
        media_urls=request.media_urls,
    )
    return {"status": "ok", "post_id": post.post_id, "created_at": post.created_at}


@app.get("/v1/me/feed")
async def get_feed(
    user_id: str = Query(..., description="User ID"),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
):
    """News Feed Retrieval API — GET /v1/me/feed"""
    posts = await service.get_feed(user_id, page=page, page_size=page_size)
    return {
        "feed": [
            {
                "post_id": p.post_id,
                "user_id": p.user_id,
                "content": p.content,
                "post_type": p.post_type,
                "like_count": p.like_count,
                "reply_count": p.reply_count,
                "share_count": p.share_count,
                "created_at": p.created_at,
            }
            for p in posts
        ],
        "page": page,
        "count": len(posts),
    }


# --- User APIs ---

@app.post("/v1/users")
async def create_user(request: CreateUserRequest):
    user = await service.create_user(request.user_id, request.username, request.display_name)
    return {"status": "ok", "user_id": user.user_id}


@app.get("/v1/users/{user_id}")
async def get_user(user_id: str):
    user = await service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user.user_id, "username": user.username, "display_name": user.display_name}


# --- Friend APIs ---

@app.post("/v1/friends")
async def add_friend(request: AddFriendRequest):
    await service.add_friend(request.user_id, request.friend_id)
    return {"status": "ok"}


# --- Action APIs ---

@app.post("/v1/actions/like")
async def like_post(request: LikeRequest):
    action = await service.like_post(request.user_id, request.post_id)
    return {"status": "ok", "action_id": action.action_id}


@app.post("/v1/actions/reply")
async def reply_post(request: ReplyRequest):
    action = await service.reply_to_post(request.user_id, request.post_id, request.content)
    return {"status": "ok", "action_id": action.action_id}


@app.post("/v1/actions/share")
async def share_post(request: ShareRequest):
    action = await service.share_post(request.user_id, request.post_id)
    return {"status": "ok", "action_id": action.action_id}


@app.get("/v1/posts/{post_id}/actions")
async def get_post_actions(post_id: str, action_type: Optional[str] = None):
    actions = await service.get_post_actions(post_id, action_type)
    return {"actions": [
        {"action_id": a.action_id, "user_id": a.user_id, "type": a.action_type, "content": a.content}
        for a in actions
    ]}


# --- Stats ---

@app.get("/v1/stats")
async def get_stats():
    db_stats = await db.get_stats()
    return {
        "service": service.stats,
        "database": db_stats,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "news-feed-system"}
