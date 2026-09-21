import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# --- Auth ---
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=6)
    nickname: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- User ---
class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    nickname: str | None
    avatar_url: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    nickname: str | None = None
    avatar_url: str | None = None


class UserSearchResult(BaseModel):
    id: uuid.UUID
    username: str
    nickname: str | None
    avatar_url: str | None


# --- Friend ---
class FriendRequest(BaseModel):
    friend_username: str


class FriendResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    nickname: str | None
    avatar_url: str | None
    status: str
    online_status: str = "offline"


class PendingRequestResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    nickname: str | None
    avatar_url: str | None
    created_at: datetime


# --- Group ---
class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    creator_id: uuid.UUID
    max_members: int
    created_at: datetime
    member_count: int = 0

    class Config:
        from_attributes = True


class GroupMemberAdd(BaseModel):
    user_id: uuid.UUID


class GroupMemberResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    nickname: str | None
    role: str


# --- Message ---
class MessageResponse(BaseModel):
    message_id: str
    sender_id: str
    receiver_id: str
    content: str
    type: str = "text"
    timestamp: int
    channel_type: str


# --- Group Member with Status ---
class GroupMemberStatusResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    nickname: str | None
    avatar_url: str | None
    role: str
    online_status: str = "offline"
    is_friend: bool = False


# --- Group Invite ---
class GroupInviteRequest(BaseModel):
    friend_ids: list[uuid.UUID]


class GroupInviteResponse(BaseModel):
    invited_ids: list[uuid.UUID]
    message: str
