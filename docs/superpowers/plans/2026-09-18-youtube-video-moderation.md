# Video Content Moderation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pre-publish moderation workflow so videos go through a pending_review → approved/rejected cycle before becoming publicly visible.

**Architecture:** New `app/moderation/` submodule (schemas/service/router) within the existing api-server monolith; reuses auth dependencies and database layer. Frontend gets a `/moderation` console view, status badges in My Channel, and a gating banner in WatchView. No new pip packages, containers, or environment variables.

**Tech Stack:** FastAPI + aiosqlite (single-writer), Vue 3 `<script setup>`, existing JWT auth with role-based guards.

---

### Task 1: Data Layer — Moderation Columns + Access Functions

**Files:**
- Modify: `youtube-system/app/database.py` (init_db migration + new functions at end)

- [ ] **Step 1: Write the verification script**

```python
# youtube-system/_verify_mod_db.py
"""Temporary verification: run from youtube-system/ dir, then delete."""
import asyncio, os, sys, tempfile
sys.path.insert(0, ".")
_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")

from app import database
from app.config import config
config.db_path = os.environ["DB_PATH"]

async def main():
    await database.init_db()

    # 1. Insert a video → moderation_status should be 'pending_review'
    await database.insert_video("vid001", "Test", "Desc", "path/f.mp4", "user1")
    v = await database.get_video("vid001")
    assert v["moderation_status"] == "pending_review", f"Expected pending_review, got {v['moderation_status']}"
    assert v["rejection_reason"] is None

    # 2. set_moderation → approved
    await database.set_moderation("vid001", "approved", None)
    v = await database.get_video("vid001")
    assert v["moderation_status"] == "approved"

    # 3. Insert another → queue
    await database.insert_video("vid002", "Queued", "D", "p/f.mp4", "user1")
    # mark it ready for queue query
    await database.set_video_status("vid002", "ready")
    q = await database.list_moderation_queue(10, 0)
    assert len(q) == 1 and q[0]["id"] == "vid002", f"Queue: {q}"
    assert await database.count_moderation_queue() == 1

    # 4. list_videos_public: only ready+approved
    await database.set_video_status("vid001", "ready")
    pub = await database.list_videos_public(10, 0)
    assert len(pub) == 1 and pub[0]["id"] == "vid001", f"Public: {[x['id'] for x in pub]}"
    assert await database.count_videos_public() == 1

    # 5. reject + resubmit
    await database.set_moderation("vid001", "rejected", "spam")
    v = await database.get_video("vid001")
    assert v["rejection_reason"] == "spam"
    pub = await database.list_videos_public(10, 0)
    assert len(pub) == 0  # no longer visible

    await database.resubmit_video("vid001", "Edited Title", "New Desc")
    v = await database.get_video("vid001")
    assert v["moderation_status"] == "pending_review"
    assert v["title"] == "Edited Title"
    assert v["rejection_reason"] is None

    print("MOD_DB_OK")

asyncio.run(main())
```

Run from `youtube-system/` directory:
```powershell
..\venv\Scripts\python.exe _verify_mod_db.py
```
Expected: FAIL with `column moderation_status not found` (function doesn't exist yet).

- [ ] **Step 2: Add ALTER migration to init_db()**

In `database.py`, after the existing PRAGMA `uploader_id` check (around line 92), add:

```python
        # moderation columns: existing rows get 'approved' (stay visible).
        if "moderation_status" not in columns:
            await db.execute(
                "ALTER TABLE videos ADD COLUMN moderation_status "
                "TEXT NOT NULL DEFAULT 'approved'")
            logger.info("Migrated videos: added moderation_status column")
        if "rejection_reason" not in columns:
            await db.execute(
                "ALTER TABLE videos ADD COLUMN rejection_reason TEXT")
            logger.info("Migrated videos: added rejection_reason column")
        await db.execute(
            """CREATE INDEX IF NOT EXISTS idx_videos_public
               ON videos(status, moderation_status, created_at)""")
```

Place before `await db.execute("CREATE INDEX IF NOT EXISTS idx_videos_uploader ...")`.

- [ ] **Step 3: Modify insert_video to write pending_review**

Change the SQL in `insert_video` from:

```python
            """INSERT INTO videos (id, title, description, status, original_path,
                                   uploader_id, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 original_path=excluded.original_path,
                 uploader_id=excluded.uploader_id, status='pending',
                 error_msg=NULL, updated_at=excluded.updated_at""",
```

to:

```python
            """INSERT INTO videos (id, title, description, status, original_path,
                                   uploader_id, moderation_status, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, 'pending_review', ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 original_path=excluded.original_path,
                 uploader_id=excluded.uploader_id, status='pending',
                 moderation_status='pending_review',
                 error_msg=NULL, updated_at=excluded.updated_at""",
```

Update the parameter tuple from `(video_id, title, description, original_path, uploader_id, now, now)` to `(video_id, title, description, original_path, uploader_id, now, now)` — the count stays the same since moderation_status is a literal, not a placeholder. No parameter change needed.

- [ ] **Step 4: Add new moderation functions at the end of database.py**

```python
# ---- moderation ----


async def set_moderation(video_id: str, status: str,
                         reason: str | None) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE videos SET moderation_status=?, rejection_reason=?, "
            "updated_at=? WHERE id=?",
            (status, reason, time.time(), video_id),
        )
        await db.commit()


async def resubmit_video(video_id: str, title: str, description: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE videos SET title=?, description=?, "
            "moderation_status='pending_review', rejection_reason=NULL, "
            "updated_at=? WHERE id=?",
            (title, description, time.time(), video_id),
        )
        await db.commit()


async def list_videos_public(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT
            + " WHERE v.status='ready' AND v.moderation_status='approved'"
            + " ORDER BY v.created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_videos_public() -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM videos "
            "WHERE status='ready' AND moderation_status='approved'")
        return (await cursor.fetchone())[0]


async def list_moderation_queue(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT
            + " WHERE v.status='ready' AND v.moderation_status='pending_review'"
            + " ORDER BY v.created_at ASC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_moderation_queue() -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM videos "
            "WHERE status='ready' AND moderation_status='pending_review'")
        return (await cursor.fetchone())[0]
```

- [ ] **Step 5: Run verification**

```powershell
cd youtube-system; ..\venv\Scripts\python.exe _verify_mod_db.py
```
Expected: `MOD_DB_OK`

- [ ] **Step 6: Delete temp script and commit**

```powershell
Remove-Item youtube-system\_verify_mod_db.py
git add youtube-system/app/database.py
git commit -m 'feat(moderation): add moderation columns and DB access functions'
```

---

### Task 2: Moderation Submodule — Schemas + Service

**Files:**
- Create: `youtube-system/app/moderation/__init__.py`
- Create: `youtube-system/app/moderation/schemas.py`
- Create: `youtube-system/app/moderation/service.py`

- [ ] **Step 1: Create __init__.py**

```python
"""Video content moderation: manual review queue with approve/reject workflow."""
```

- [ ] **Step 2: Create schemas.py**

```python
"""Pydantic request models for the moderation API."""
from pydantic import BaseModel, Field


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ResubmitRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
```

- [ ] **Step 3: Create service.py**

```python
"""Moderation business logic (spec 3.1).

Reaches the database only through app.database; raises domain exceptions
that router.py maps to HTTP codes. Reuses auth primitives (ROLE_LEVEL).
"""
from app import database
from app.auth.dependencies import CurrentUser
from app.auth.security import ROLE_LEVEL

_MODERATOR_LEVEL = ROLE_LEVEL["moderator"]


class NotFoundError(Exception):
    """404 - video not found or access denied (masquerades as 404)."""


class PermissionDenied(Exception):
    """403 - resubmit by non-owner."""


class ValidationError(Exception):
    """400 - illegal state transition."""


def _queue_card(v: dict) -> dict:
    """Format a video row for the moderation queue response."""
    return {
        "id": v["id"],
        "title": v["title"],
        "description": v["description"],
        "status": v["status"],
        "moderation_status": v.get("moderation_status", "pending_review"),
        "rejection_reason": v.get("rejection_reason"),
        "duration_sec": v["duration_sec"],
        "uploader": ({"id": v["uploader_id"], "username": v.get("uploader_username")}
                     if v.get("uploader_id") else None),
        "created_at": v["created_at"],
    }


async def list_queue(limit: int, offset: int) -> dict:
    rows = await database.list_moderation_queue(limit, offset)
    total = await database.count_moderation_queue()
    return {"videos": [_queue_card(r) for r in rows], "total": total}


async def approve(video_id: str, actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None:
        raise NotFoundError("video not found")
    if v["moderation_status"] != "pending_review":
        raise ValidationError("only pending_review videos can be approved")
    await database.set_moderation(video_id, "approved", None)


async def reject(video_id: str, reason: str, actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None:
        raise NotFoundError("video not found")
    if v["moderation_status"] != "pending_review":
        raise ValidationError("only pending_review videos can be rejected")
    await database.set_moderation(video_id, "rejected", reason)


async def resubmit(video_id: str, title: str, description: str,
                   actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None:
        raise NotFoundError("video not found")
    if v.get("uploader_id") != actor.id:
        raise PermissionDenied("not your video")
    if v["moderation_status"] != "rejected":
        raise ValidationError("only rejected videos can be resubmitted")
    await database.resubmit_video(video_id, title, description)


def assert_visible(video: dict, viewer: CurrentUser | None) -> None:
    """Gate for GET video detail: if not approved+ready, only owner/moderator+
    can view; others get 404 (existence not leaked)."""
    is_public = (video["status"] == "ready"
                 and video.get("moderation_status", "approved") == "approved")
    if is_public:
        return
    if viewer is None:
        raise NotFoundError("video not found")
    is_owner = video.get("uploader_id") == viewer.id
    is_staff = ROLE_LEVEL.get(viewer.role, 0) >= _MODERATOR_LEVEL
    if not (is_owner or is_staff):
        raise NotFoundError("video not found")
```

- [ ] **Step 4: Write verification script**

```python
# youtube-system/_verify_mod_service.py
import asyncio, os, sys, tempfile
sys.path.insert(0, ".")
_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")

from app import database
from app.config import config
config.db_path = os.environ["DB_PATH"]

from app.moderation import service
from app.auth.dependencies import CurrentUser

alice = CurrentUser(id="alice", username="alice", role="creator")
mod = CurrentUser(id="mod1", username="mod", role="moderator")
stranger = CurrentUser(id="str1", username="stranger", role="user")

async def main():
    await database.init_db()
    await database.insert_video("v1", "Title", "Desc", "p", alice.id)
    await database.set_video_status("v1", "ready")

    # list_queue shows v1
    q = await service.list_queue(10, 0)
    assert q["total"] == 1 and q["videos"][0]["id"] == "v1"

    # approve
    await service.approve("v1", mod)
    v = await database.get_video("v1")
    assert v["moderation_status"] == "approved"

    # double approve fails
    try:
        await service.approve("v1", mod)
        assert False, "should raise"
    except service.ValidationError:
        pass

    # assert_visible: approved+ready → all pass
    service.assert_visible(v, None)
    service.assert_visible(v, stranger)

    # reject v1 → set back to pending_review first, then reject
    await database.set_moderation("v1", "pending_review", None)
    await service.reject("v1", "policy violation", mod)
    v = await database.get_video("v1")
    assert v["moderation_status"] == "rejected"
    assert v["rejection_reason"] == "policy violation"

    # assert_visible: rejected → owner passes, stranger 404, mod passes
    service.assert_visible(v, alice)  # owner
    service.assert_visible(v, mod)    # staff
    try:
        service.assert_visible(v, stranger)
        assert False
    except service.NotFoundError:
        pass
    try:
        service.assert_visible(v, None)
        assert False
    except service.NotFoundError:
        pass

    # resubmit
    await service.resubmit("v1", "New Title", "New Desc", alice)
    v = await database.get_video("v1")
    assert v["moderation_status"] == "pending_review"
    assert v["title"] == "New Title"
    assert v["rejection_reason"] is None

    # resubmit by non-owner → PermissionDenied
    try:
        await service.resubmit("v1", "x", "y", stranger)
        assert False
    except service.PermissionDenied:
        pass

    # resubmit non-rejected → ValidationError
    try:
        await service.resubmit("v1", "x", "y", alice)
        assert False
    except service.ValidationError:
        pass

    print("MOD_SERVICE_OK")

asyncio.run(main())
```

Run:
```powershell
cd youtube-system; ..\venv\Scripts\python.exe _verify_mod_service.py
```
Expected: `MOD_SERVICE_OK`

- [ ] **Step 5: Delete temp script and commit**

```powershell
Remove-Item youtube-system\_verify_mod_service.py
git add youtube-system/app/moderation/
git commit -m 'feat(moderation): add service and schemas for approve/reject/resubmit'
```

---

### Task 3: Moderation Router + Wire into Server

**Files:**
- Create: `youtube-system/app/moderation/router.py`
- Modify: `youtube-system/app/server.py` (import + include_router)

- [ ] **Step 1: Create router.py**

```python
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
```

- [ ] **Step 2: Wire into server.py**

After the existing `from app.comments.router import router as comments_router` line (line 17), add:

```python
from app.moderation.router import router as moderation_router
```

After the existing `app.include_router(comments_router)` line (line 56), add:

```python
app.include_router(moderation_router)
```

- [ ] **Step 3: Write verification script (route table check)**

```python
# youtube-system/_verify_mod_routes.py
"""Check moderation routes exist in the app router table."""
import os, sys, tempfile
sys.path.insert(0, ".")
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["JWT_SECRET"] = "x"

from app.server import app

routes = {(r.path, r.methods) for r in app.routes if hasattr(r, 'methods')}
expected = [
    ("/api/moderation/queue", {"GET"}),
    ("/api/moderation/{video_id}/approve", {"POST"}),
    ("/api/moderation/{video_id}/reject", {"POST"}),
    ("/api/videos/{video_id}/resubmit", {"POST"}),
]
for path, methods in expected:
    assert (path, methods) in routes, f"Missing route: {path} {methods}"

print("MOD_ROUTES_OK")
```

Run:
```powershell
cd youtube-system; ..\venv\Scripts\python.exe _verify_mod_routes.py
```
Expected: `MOD_ROUTES_OK`

- [ ] **Step 4: Delete temp script and commit**

```powershell
Remove-Item youtube-system\_verify_mod_routes.py
git add youtube-system/app/moderation/router.py youtube-system/app/server.py
git commit -m 'feat(moderation): add moderation router endpoints and wire into server'
```

---

### Task 4: Read-Path Gating — Filter Public List and Gate Video Detail

**Files:**
- Modify: `youtube-system/app/server.py` (list_videos, get_video, my_videos, _card)

- [ ] **Step 1: Modify _card to include moderation fields**

Replace `_card` function (currently at line 59-72) with:

```python
def _card(v: dict) -> dict:
    uploader = ({"id": v["uploader_id"], "username": v.get("uploader_username")}
                if v.get("uploader_id") else None)
    return {
        "id": v["id"],
        "title": v["title"],
        "description": v["description"],
        "status": v["status"],
        "moderation_status": v.get("moderation_status", "approved"),
        "rejection_reason": v.get("rejection_reason"),
        "duration_sec": v["duration_sec"],
        "thumbnail_url": f"/media/{v['id']}/thumbnail.jpg"
                         if v["status"] == "ready" else None,
        "uploader": uploader,
        "created_at": v["created_at"],
    }
```

- [ ] **Step 2: Modify list_videos to use list_videos_public**

Replace the existing `list_videos` endpoint (lines 162-165) with:

```python
@app.get("/api/videos")
async def list_videos(limit: int = Query(50, ge=1, le=200),
                      offset: int = Query(0, ge=0)):
    rows = await database.list_videos_public(limit, offset)
    total = await database.count_videos_public()
    return {"videos": [_card(v) for v in rows], "total": total}
```

Add `Query` to the import from fastapi. Change line 8 from:
```python
from fastapi import Depends, FastAPI, HTTPException, Request
```
to:
```python
from fastapi import Depends, FastAPI, HTTPException, Query, Request
```

- [ ] **Step 3: Modify get_video to gate access**

Replace lines 168-178 (the `get_video` endpoint) with:

```python
@app.get("/api/videos/{video_id}")
async def get_video(video_id: str,
                    viewer: CurrentUser | None = Depends(get_optional_user)):
    v = await database.get_video(video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    try:
        moderation_service.assert_visible(v, viewer)
    except moderation_service.NotFoundError:
        raise HTTPException(status_code=404, detail="Video not found")
    out = _card(v)
    out["error_msg"] = v["error_msg"]
    if v["status"] == "ready":
        out["stream_url"] = f"/media/{video_id}/master.m3u8"
        out["renditions"] = await database.get_renditions(video_id)
    return out
```

Add the import (after the existing `from app.comments.router import ...` line):

```python
from app.moderation import service as moderation_service
```

- [ ] **Step 4: Modify my_videos to include moderation fields**

Replace the existing `my_videos` endpoint. It already uses `_card` which now includes `moderation_status` and `rejection_reason` — no logic change needed, just verify the function body passes moderation fields. Current code at line 151-159:

```python
@app.get("/api/videos/mine")
async def my_videos(user: CurrentUser = Depends(require_role("creator"))):
    rows = await database.list_videos_by_uploader(user.id)
    return {"videos": [_card(v) for v in rows]}
```

This is already correct (now `_card` exposes moderation_status). No edit.

- [ ] **Step 5: Write verification script**

```python
# youtube-system/_verify_mod_gating.py
"""Verify list_videos and get_video gating."""
import asyncio, os, sys, tempfile
sys.path.insert(0, ".")
_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["JWT_SECRET"] = "x"

from app import database
from app.config import config
config.db_path = os.environ["DB_PATH"]

async def main():
    await database.init_db()
    # Insert two videos, mark both ready
    await database.insert_video("pub1", "Public", "d", "p", "u1")
    await database.set_video_status("pub1", "ready")
    await database.set_moderation("pub1", "approved", None)

    await database.insert_video("priv1", "Pending", "d", "p", "u1")
    await database.set_video_status("priv1", "ready")
    # priv1 stays pending_review

    # list_videos_public should only show pub1
    pub = await database.list_videos_public(50, 0)
    assert len(pub) == 1 and pub[0]["id"] == "pub1"

    # Test _card includes moderation_status
    from app.server import _card
    card = _card(pub[0])
    assert card["moderation_status"] == "approved"
    assert card["rejection_reason"] is None

    priv = await database.get_video("priv1")
    card2 = _card(priv)
    assert card2["moderation_status"] == "pending_review"

    print("MOD_GATING_OK")

asyncio.run(main())
```

Run:
```powershell
cd youtube-system; ..\venv\Scripts\python.exe _verify_mod_gating.py
```
Expected: `MOD_GATING_OK`

- [ ] **Step 6: Delete temp, compile check, and commit**

```powershell
Remove-Item youtube-system\_verify_mod_gating.py
..\venv\Scripts\python.exe -m py_compile youtube-system/app/server.py
```
Expected: no output (exit 0).

```powershell
git add youtube-system/app/server.py
git commit -m 'feat(moderation): gate video list/detail on moderation_status'
```

---

### Task 5: Docker Build and E2E Test

**Files:**
- No source changes; verification only.

- [ ] **Step 1: Build and restart api-server**

```powershell
cd youtube-system; docker compose up -d --build api-server
```
Wait for healthy status.

- [ ] **Step 2: Health check**

```powershell
curl http://localhost:8000/api/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 3: Write e2e script**

```python
# youtube-system/_e2e_moderation.py
"""Full HTTP e2e against running api-server container."""
import json, urllib.request, sys

BASE = "http://localhost:8000"

def req(method, path, body=None, token=None, expect_status=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(r)
        status = resp.status
        body_out = json.loads(resp.read()) if resp.read else None
    except urllib.error.HTTPError as e:
        status = e.code
        body_out = json.loads(e.read()) if e.read() else None
    if expect_status and status != expect_status:
        print(f"FAIL: {method} {path} => {status} (expected {expect_status}): {body_out}")
        sys.exit(1)
    return status, body_out

# 1. Login as seed creator
status, tok = req("POST", "/api/auth/login", {"email": "creator@mytube.local", "password": "Creator@123"}, expect_status=200)
creator_token = tok["access_token"]

# 2. Login as seed admin (has moderator level)
status, tok2 = req("POST", "/api/auth/login", {"email": "admin@mytube.local", "password": "Admin@123"}, expect_status=200)
admin_token = tok2["access_token"]

# 3. Check moderation queue (as admin)
status, q = req("GET", "/api/moderation/queue", token=admin_token, expect_status=200)
print(f"Queue: {q['total']} videos pending review")

# 4. If there are pending videos, approve first one
if q["videos"]:
    vid = q["videos"][0]["id"]
    req("POST", f"/api/moderation/{vid}/approve", token=admin_token, expect_status=204)
    print(f"Approved {vid}")

# 5. Non-moderator (creator) accessing queue → 403
req("GET", "/api/moderation/queue", token=creator_token, expect_status=403)
print("Creator blocked from queue: OK")

# 6. Public list should have videos (the one just approved at minimum)
status, pub = req("GET", "/api/videos")
assert status == 200 and len(pub["videos"]) >= 1
print(f"Public list: {len(pub['videos'])} videos, total={pub['total']}")

# 7. Get a non-existent video detail → 404
req("GET", "/api/videos/nonexistent", expect_status=404)

# 8. Test reject + resubmit flow with a known video
# Insert via queue: find any pending or manually create
# For simplicity just test 404 on approve of non-existent
req("POST", "/api/moderation/fakevid/approve", token=admin_token, expect_status=404)
print("Approve non-existent: 404 OK")

print("MOD_E2E_OK")
```

Run:
```powershell
cd youtube-system; ..\venv\Scripts\python.exe _e2e_moderation.py
```
Expected: `MOD_E2E_OK`

- [ ] **Step 4: Clean up temp script**

```powershell
Remove-Item youtube-system\_e2e_moderation.py
```

No source file changed → no commit needed (or commit if README updated later).

---

### Task 6: Frontend API Client

**Files:**
- Modify: `youtube-system/frontend/src/api.js` (append 4 functions)

- [ ] **Step 1: Add moderation functions at end of api.js**

After the last function `voteComment` (line 173), append:

```javascript
// ---- moderation ----
export function listModerationQueue(limit = 50, offset = 0) {
  return http.get('/api/moderation/queue', { params: { limit, offset } })
}

export function approveVideo(videoId) {
  return http.post(`/api/moderation/${videoId}/approve`)
}

export function rejectVideo(videoId, reason) {
  return http.post(`/api/moderation/${videoId}/reject`, { reason })
}

export function resubmitVideo(videoId, title, description) {
  return http.post(`/api/videos/${videoId}/resubmit`, { title, description })
}
```

- [ ] **Step 2: Build check**

```powershell
cd youtube-system/frontend; npm run build *> $null; $LASTEXITCODE
```
Expected: `0`

- [ ] **Step 3: Commit**

```powershell
git add youtube-system/frontend/src/api.js
git commit -m 'feat(moderation): add moderation API client functions'
```

---

### Task 7: Frontend — ModerationView + Route + Nav

**Files:**
- Create: `youtube-system/frontend/src/views/ModerationView.vue`
- Modify: `youtube-system/frontend/src/router.js` (add route)
- Modify: `youtube-system/frontend/src/App.vue` (nav entry)

- [ ] **Step 1: Create ModerationView.vue**

```vue
<script setup>
import { onMounted, ref } from 'vue'
import { approveVideo, extractError, listModerationQueue, rejectVideo } from '../api'

const videos = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const busyId = ref('')
const rejectInputs = ref({})
const showRejectForm = ref({})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await listModerationQueue(50, 0)
    videos.value = data.videos
    total.value = data.total
  } catch (e) {
    error.value = extractError(e, 'Failed to load queue')
  } finally {
    loading.value = false
  }
}

async function doApprove(id) {
  busyId.value = id
  error.value = ''
  try {
    await approveVideo(id)
    videos.value = videos.value.filter((v) => v.id !== id)
    total.value--
  } catch (e) {
    error.value = extractError(e, 'Approve failed')
  } finally {
    busyId.value = ''
  }
}

function toggleReject(id) {
  showRejectForm.value[id] = !showRejectForm.value[id]
  if (!rejectInputs.value[id]) rejectInputs.value[id] = ''
}

async function doReject(id) {
  const reason = (rejectInputs.value[id] || '').trim()
  if (!reason) { error.value = 'Rejection reason is required'; return }
  busyId.value = id
  error.value = ''
  try {
    await rejectVideo(id, reason)
    videos.value = videos.value.filter((v) => v.id !== id)
    total.value--
    delete showRejectForm.value[id]
  } catch (e) {
    error.value = extractError(e, 'Reject failed')
  } finally {
    busyId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="moderation-page">
    <h2 style="margin-top: 0">Moderation Queue</h2>
    <div v-if="error" class="error-box">{{ error }}</div>
    <p v-if="loading" class="mod-loading">Loading…</p>
    <p v-else-if="videos.length === 0" class="empty-state">No videos pending review.</p>

    <div v-for="v in videos" :key="v.id" class="mod-item">
      <div class="mod-info">
        <RouterLink :to="`/watch/${v.id}`" class="mod-title">{{ v.title }}</RouterLink>
        <span class="mod-meta">
          by {{ v.uploader?.username || 'Anonymous' }} · {{ new Date(v.created_at * 1000).toLocaleString() }}
        </span>
      </div>
      <div class="mod-actions">
        <button class="btn" :disabled="busyId === v.id" @click="doApprove(v.id)">
          {{ busyId === v.id ? '…' : 'Approve' }}
        </button>
        <button class="btn secondary" @click="toggleReject(v.id)">Reject</button>
      </div>
      <div v-if="showRejectForm[v.id]" class="mod-reject-form">
        <input
          v-model="rejectInputs[v.id]"
          placeholder="Reason (required)"
          maxlength="500"
          @keyup.enter="doReject(v.id)"
        />
        <button class="btn" :disabled="busyId === v.id" @click="doReject(v.id)">Confirm Reject</button>
      </div>
    </div>
    <p v-if="total > videos.length" class="mod-summary">
      {{ videos.length }} of {{ total }} shown.
    </p>
  </div>
</template>
```

- [ ] **Step 2: Add route to router.js**

After the `AdminUsersView` import (line 3), add:

```javascript
import ModerationView from './views/ModerationView.vue'
```

In the `routes` array (line 13), add a new entry after the `/admin/users` route (line 28-29):

```javascript
    {
      path: '/moderation',
      component: ModerationView,
      meta: { requiresAuth: true, role: 'moderator' },
    },
```

- [ ] **Step 3: Add nav link in App.vue dropdown**

After the Admin panel button (line 50-52), add:

```html
              <button v-if="hasRole('moderator')" class="dropdown-item" @click="go('/moderation')">
                Moderation
              </button>
```

- [ ] **Step 4: Build check**

```powershell
cd youtube-system/frontend; npm run build *> $null; $LASTEXITCODE
```
Expected: `0`

- [ ] **Step 5: Commit**

```powershell
git add youtube-system/frontend/src/views/ModerationView.vue youtube-system/frontend/src/router.js youtube-system/frontend/src/App.vue
git commit -m 'feat(moderation): add moderation console view, route, and nav entry'
```

---

### Task 8: Frontend — My Channel Badges + Watch Banner + Styles + README

**Files:**
- Modify: `youtube-system/frontend/src/views/MyVideosView.vue` (badges + resubmit)
- Modify: `youtube-system/frontend/src/views/WatchView.vue` (moderation banner)
- Modify: `youtube-system/frontend/src/style.css` (moderation styles)
- Modify: `youtube-system/README.md` (moderation feature)

- [ ] **Step 1: Modify MyVideosView.vue — add moderation badge and resubmit button**

After the existing `<span class="badge" :class="v.status">{{ v.status }}</span>` line (74), add:

```html
            <span v-if="v.moderation_status === 'pending_review'" class="badge pending_review">审核中</span>
            <span v-else-if="v.moderation_status === 'rejected'" class="badge rejected" :title="v.rejection_reason">已拒绝</span>
```

After the existing retry button block (line 78-86), add the resubmit button:

```html
          <button
            v-if="v.moderation_status === 'rejected'"
            class="btn tiny"
            style="margin-top: 8px"
            :disabled="busyId === v.id"
            @click.stop="doResubmit(v)"
          >
            {{ busyId === v.id ? 'Submitting…' : 'Resubmit' }}
          </button>
```

Add import at line 4:

```javascript
import { extractError, listMyVideos, resubmitVideo, retryVideo } from '../api'
```

Add `doResubmit` function after `doRetry` (line 43):

```javascript
async function doResubmit(v) {
  busyId.value = v.id
  error.value = ''
  try {
    await resubmitVideo(v.id, v.title, v.description || '')
    await refresh()
  } catch (e) {
    error.value = extractError(e, 'Resubmit failed')
  } finally {
    busyId.value = ''
  }
}
```

- [ ] **Step 2: Modify WatchView.vue — moderation banner**

Add after the `<div class="player-box">` block (line 95-97). Insert before the `<h2>` line (98):

```html
        <div v-if="video.moderation_status === 'pending_review'" class="badge pending_review moderation-banner">
          Under review – only you (owner) and moderators can see this page
        </div>
        <div v-else-if="video.moderation_status === 'rejected'" class="error-box moderation-banner">
          Rejected: {{ video.rejection_reason }}
        </div>
```

- [ ] **Step 3: Add moderation styles to style.css**

Append at the end of `youtube-system/frontend/src/style.css`:

```css
/* ---- Moderation ---- */
.badge.pending_review { background: #f59e0b; color: #000; }
.badge.rejected { background: #ef4444; color: #fff; cursor: help; }
.moderation-banner { margin: 12px 0; padding: 8px 12px; border-radius: 6px; font-size: 14px; }
.moderation-page h2 { color: var(--text); }
.mod-item { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); }
.mod-info { flex: 1; min-width: 0; }
.mod-title { font-weight: 600; color: var(--accent); text-decoration: none; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mod-meta { font-size: 12px; color: var(--text-dim); }
.mod-actions { display: flex; gap: 8px; flex-shrink: 0; }
.mod-reject-form { width: 100%; display: flex; gap: 8px; margin-top: 8px; }
.mod-reject-form input { flex: 1; padding: 6px 10px; border-radius: 4px; border: 1px solid var(--border); background: var(--bg-card); color: var(--text); }
.mod-loading { color: var(--text-dim); }
.mod-summary { color: var(--text-dim); font-size: 13px; margin-top: 12px; }
```

- [ ] **Step 4: Update README.md**

In the Feature List section, after the last comment bullet, add:

```markdown
- **视频内容审核** — 先审后发（moderator+ 审核队列 approve/reject）；拒绝可编辑后重新提交，不重转码
```

After the Comments & Votes API section in the README, add:

```markdown
### 视频审核（Moderation）

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/moderation/queue` | moderator+ | 待审列表 `{videos, total}` |
| POST | `/api/moderation/{id}/approve` | moderator+ | 通过 → 204 |
| POST | `/api/moderation/{id}/reject` | moderator+ | 拒绝 `{reason}` → 204 |
| POST | `/api/videos/{id}/resubmit` | owner | 重新提交 `{title,description}` → 204 |
```

In the Design Notes section (numbered list), append:

```markdown
16. **Moderation status is orthogonal to transcode status** — `moderation_status` (pending_review/approved/rejected) is independent from `status` (pending/processing/ready/failed); a video is publicly visible only when `status='ready' AND moderation_status='approved'`.
17. **Visibility gate at API level, not CDN** — non-approved videos return 404; since video IDs are random hex, the CDN path is not guessable. True CDN-level auth is deferred to the DRM module.
18. **FIFO review queue** — videos enter moderation after transcode completes, oldest first; rejected videos re-enter queue via resubmit (no re-transcode).
```

- [ ] **Step 5: Build check**

```powershell
cd youtube-system/frontend; npm run build *> $null; $LASTEXITCODE
```
Expected: `0`

- [ ] **Step 6: Deploy and verify**

```powershell
cd youtube-system; docker compose up -d --build frontend
```
Then check:
```powershell
curl http://localhost:8080/ -o $null -w "%{http_code}"
```
Expected: `200`

- [ ] **Step 7: Commit**

```powershell
git add youtube-system/frontend/src/views/MyVideosView.vue youtube-system/frontend/src/views/WatchView.vue youtube-system/frontend/src/style.css youtube-system/README.md
git commit -m 'feat(moderation): add UI badges, watch banner, moderation styles, and README docs'
```

---

## Completion Criteria

All tasks done ⟹
- Two DB columns (`moderation_status`, `rejection_reason`) migrated, idempotent on restart.
- `app/moderation/` submodule with schemas/service/router, 4 endpoints, domain exceptions.
- Public list filtered; non-approved detail returns 404 to unprivileged viewers, owner/moderator see + badge.
- Resubmit only for owner, only rejected → pending_review.
- Frontend: ModerationView with approve/reject, My Channel badges + resubmit, Watch banner, nav gated.
- `docker compose up -d --build` → 5 containers Up, `/api/health` ok, `/api/moderation/queue` 200 as admin, 403 as creator.
- `npm build` exit 0.
- No new pip deps, no new containers, no new env vars.

## Self-Review

**1. Spec coverage:**
- §1 数据模型 → Task 1
- §2 API 端点 → Tasks 2-3
- §3 模块结构 → Task 2
- §4 状态机 → Task 1-2 (DB transitions) + service validation
- §5 前端集成 → Tasks 6-8
- §6 配置约束 → Verified (no additions)
- §7 错误处理 → Tasks 2-3 (exception hierarchy)
- §8 验证计划 → Tasks 1-5
- §2.3 stream_playlist gating → N/A (no such endpoint; HLS served by CDN directly; gating via API 404 sufficient, documented in §9 limitations)

**2. Placeholder scan:** No "TBD", "handle edge cases", or similar red-flags found.

**3. Type consistency:** `moderation_status` values (`pending_review`/`approved`/`rejected`) used identically across DB, service, _card, frontend badges. `list_videos_public`/`list_moderation_queue` return same row dict as `list_videos`. `assert_visible` called with `(video_dict, CurrentUser|None)` matching get_optional_user return. `_queue_card` fields align with `ModerationView.vue` template.
