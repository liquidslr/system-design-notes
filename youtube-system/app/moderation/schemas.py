"""Pydantic request models for the moderation API."""
from pydantic import BaseModel, Field


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ResubmitRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
