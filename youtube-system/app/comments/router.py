"""HTTP layer for /api/videos/{id}/comments and /api/comments/* (spec 4).

Reuses auth dependencies; maps comments-service domain exceptions to codes.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth.dependencies import (CurrentUser, get_current_user,
                                   get_optional_user)
from app.comments import schemas, service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/videos/{video_id}/comments")
async def list_comments(video_id: str,
                        sort: str = Query("top", pattern="^(top|new)$"),
                        limit: int = Query(20, ge=1, le=50),
                        offset: int = Query(0, ge=0),
                        user: CurrentUser | None = Depends(get_optional_user)):
    try:
        return await service.list_comments(video_id, sort, limit, offset, user)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/comments/{comment_id}/replies")
async def list_replies(comment_id: str,
                       limit: int = Query(20, ge=1, le=50),
                       offset: int = Query(0, ge=0),
                       user: CurrentUser | None = Depends(get_optional_user)):
    try:
        return await service.list_replies(comment_id, limit, offset, user)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/videos/{video_id}/comments",
             status_code=201, response_model=schemas.CommentOut)
async def create_comment(video_id: str, req: schemas.CommentCreateRequest,
                         user: CurrentUser = Depends(get_current_user)):
    try:
        return await service.create_comment(
            video_id, user.id, req.content, req.reply_to)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: str,
                         user: CurrentUser = Depends(get_current_user)):
    try:
        await service.delete_comment(comment_id, user.id, user.role)
        return Response(status_code=204)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.PermissionDenied as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.put("/api/comments/{comment_id}/vote")
async def vote_comment(comment_id: str, req: schemas.VoteRequest,
                       user: CurrentUser = Depends(get_current_user)):
    try:
        return await service.vote(comment_id, user.id, req.value)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
