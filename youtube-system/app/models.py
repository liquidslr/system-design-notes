"""Pydantic models for api-server request/response validation."""
from pydantic import BaseModel, Field


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    size: int = Field(..., gt=0)
    content_type: str = "video/mp4"


class UploadUrlResponse(BaseModel):
    token: str
    video_id: str
    upload_path: str
    expires_in: int


class VideoCreateRequest(BaseModel):
    video_id: str = Field(..., min_length=8, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    filename: str = Field(..., min_length=1, max_length=255)  # 用于推导扩展名
