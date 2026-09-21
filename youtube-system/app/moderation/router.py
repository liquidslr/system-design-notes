"""HTTP layer for /api/moderation/* and /api/videos/{id}/resubmit.

Maps moderation-service domain exceptions to HTTP status codes.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.moderation import schemas, service

router = APIRouter()


@router.get("/api/moderation/queue")
async def list_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: CurrentUser = Depends(require_role("moderator")),
):
    return await service.list_queue(limit, offset)


@router.post("/api/moderation/{video_id}/approve", status_code=204)
async def approve(video_id: str,
                  user: CurrentUser = Depends(require_role("moderator"))):
    try:
        await service.approve(video_id, user)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(status_code=204)


@router.post("/api/moderation/{video_id}/reject", status_code=204)
async def reject(video_id: str, req: schemas.RejectRequest,
                 user: CurrentUser = Depends(require_role("moderator"))):
    try:
        await service.reject(video_id, req.reason, user)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(status_code=204)


@router.post("/api/videos/{video_id}/resubmit", status_code=204)
async def resubmit(video_id: str, req: schemas.ResubmitRequest,
                   user: CurrentUser = Depends(get_current_user)):
    try:
        await service.resubmit(video_id, req.title, req.description, user)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except service.PermissionDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(status_code=204)
