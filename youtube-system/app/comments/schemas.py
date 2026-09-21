"""Pydantic models for the comments + likes API (spec 4)."""
from pydantic import BaseModel, Field

CONTENT_MAX = 1000
DELETED_PLACEHOLDER = "This comment was deleted."


class CommentCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=CONTENT_MAX)
    reply_to: str | None = Field(None, min_length=8, max_length=64)


class VoteRequest(BaseModel):
    # 0 = cancel; range check mirrors spec 4. Out-of-range -> 422 via ge/le.
    value: int = Field(..., ge=-1, le=1)


class CommentAuthor(BaseModel):
    id: str | None
    username: str


class CommentOut(BaseModel):
    id: str
    video_id: str
    author: CommentAuthor
    content: str
    status: str
    parent_id: str | None
    root_id: str | None
    like_count: int
    dislike_count: int
    score: int
    reply_count: int = 0
    my_vote: int = 0
    created_at: float
