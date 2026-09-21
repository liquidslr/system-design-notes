"""
Core data models for the News Feed System.

Design doc:
- Users publish posts (text, images, videos)
- Friends see posts in reverse chronological order
- Actions: likes, replies, shares
- Counters: likes count, replies count, followers count
"""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PostType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    LINK = "link"


class ActionType(str, Enum):
    LIKE = "like"
    REPLY = "reply"
    SHARE = "share"


@dataclass
class User:
    user_id: str
    username: str
    display_name: str
    created_at: float = field(default_factory=time.time)
    follower_count: int = 0
    following_count: int = 0


@dataclass
class Post:
    post_id: str
    user_id: str
    content: str
    post_type: PostType = PostType.TEXT
    media_urls: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    like_count: int = 0
    reply_count: int = 0
    share_count: int = 0


@dataclass
class Friendship:
    user_id: str
    friend_id: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Action:
    action_id: str
    user_id: str
    post_id: str
    action_type: ActionType
    content: Optional[str] = None  # For replies
    created_at: float = field(default_factory=time.time)


@dataclass
class FeedItem:
    """An item in a user's news feed (stores post_id + author_id)."""
    post_id: str
    user_id: str  # Author
    created_at: float = field(default_factory=time.time)
