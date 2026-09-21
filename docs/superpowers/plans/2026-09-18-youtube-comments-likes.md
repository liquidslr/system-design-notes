# MyTube 评论与点赞 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `youtube-system` 新增「视频评论 + 1 级回复 + 评论赞/踩（互斥、可切换/取消）」，读公开、登录可写、作者或 moderator+ 可软删。

**Architecture:** 模块化单体——在现有 `api-server` 内新增 `app/comments/` 子包（`schemas/service/router`），复用 `app/auth/dependencies` 的鉴权与 `app/auth/security.ROLE_LEVEL`；投票计数用 `comments` 表冗余列 + `comment_votes` 表，单事务更新（api-server 仍是 SQLite 唯一写者）。前端抽 `Comments.vue`/`CommentItem.vue` 挂到 Watch 页，`api.js` 追加 5 个函数。不新增容器、无新增 pip 依赖。

**Tech Stack:** FastAPI + aiosqlite（SQLite）、Redis（本轮 comments 不使用）、Pydantic v2、Vue 3 `<script setup>` + vue-router + axios。

**参考规格：** `docs/superpowers/specs/2026-09-18-youtube-comments-likes-design.md`

---

## 文件结构（本计划创建/修改）

**后端**
- Modify: `youtube-system/app/database.py` — `init_db()` 追加 `comments`/`comment_votes` 两表；新增评论/投票数据访问函数
- Create: `youtube-system/app/comments/__init__.py` — 包声明
- Create: `youtube-system/app/comments/schemas.py` — `CommentCreateRequest`/`VoteRequest`/`CommentOut` + 常量
- Create: `youtube-system/app/comments/service.py` — 业务逻辑，抛领域异常
- Create: `youtube-system/app/comments/router.py` — `/api` 端点，异常→HTTP 码
- Modify: `youtube-system/app/server.py` — `include_router(comments_router)`

**前端**
- Modify: `youtube-system/frontend/src/api.js` — 追加 5 个评论/投票函数
- Create: `youtube-system/frontend/src/components/CommentItem.vue`
- Create: `youtube-system/frontend/src/components/Comments.vue`
- Modify: `youtube-system/frontend/src/views/WatchView.vue` — 挂载 `<Comments>`
- Modify: `youtube-system/frontend/src/style.css` — 评论区块样式

**文档/部署**
- Modify: `youtube-system/README.md` — 评论点赞章节
- 临时脚本（验证后删）：`_verify_comments_db.py`、`_verify_comments_read.py`、`_verify_comments_vote.py`、`_verify_comment_routes.py`、`_e2e_comments.py`

**验证环境约定**（沿用仓库既有风格，非 pytest）：
- 纯逻辑验证用临时 SQLite 文件直连 `database`+`service`，跑完即删
- 命令从 `youtube-system/` 目录运行，venv python 为 `..\venv\Scripts\python.exe`
- PowerShell 不支持 `&&`，用 `;`；commit 消息避免括号/管道，用单引号

---

## Task 1: 数据层——两表 + 评论/投票数据访问函数

**Files:**
- Modify: `youtube-system/app/database.py`

- [ ] **Step 1: 在 `init_db()` 的 `executescript` 内追加两表**

在 `app/database.py` 的 `executescript(""" ... """)` 中，`users` 表建表语句**之后**、结束三引号之前，插入：

```sql
            CREATE TABLE IF NOT EXISTS comments (
                id            TEXT PRIMARY KEY,
                video_id      TEXT NOT NULL REFERENCES videos(id),
                author_id     TEXT NOT NULL REFERENCES users(id),
                parent_id     TEXT REFERENCES comments(id),
                root_id       TEXT REFERENCES comments(id),
                body          TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'active',
                like_count    INTEGER NOT NULL DEFAULT 0,
                dislike_count INTEGER NOT NULL DEFAULT 0,
                score         INTEGER NOT NULL DEFAULT 0,
                created_at    REAL NOT NULL,
                updated_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comments_thread
                ON comments(root_id, status);
            CREATE INDEX IF NOT EXISTS idx_comments_sort
                ON comments(video_id, status, score, created_at);
            CREATE TABLE IF NOT EXISTS comment_votes (
                user_id    TEXT NOT NULL REFERENCES users(id),
                comment_id TEXT NOT NULL REFERENCES comments(id),
                value      INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (user_id, comment_id)
            );
            CREATE INDEX IF NOT EXISTS idx_votes_comment
                ON comment_votes(comment_id);
```

- [ ] **Step 2: 追加评论 SELECT 片段与数据访问函数**

在 `app/database.py` 末尾（`set_user_status` 之后）追加：

```python
_COMMENT_SELECT = """
    SELECT c.*, u.username AS author_username
    FROM comments c LEFT JOIN users u ON c.author_id = u.id
"""


async def insert_comment(comment_id: str, video_id: str, author_id: str,
                         body: str, parent_id: str | None,
                         root_id: str | None) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO comments (id, video_id, author_id, parent_id, root_id,
                                      body, status, like_count, dislike_count,
                                      score, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', 0, 0, 0, ?, ?)""",
            (comment_id, video_id, author_id, parent_id, root_id, body, now, now),
        )
        await db.commit()


async def get_comment(comment_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _COMMENT_SELECT + " WHERE c.id = ?", (comment_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_top_comments(video_id: str, sort: str, limit: int,
                            offset: int) -> list[dict]:
    order = ("c.score DESC, c.created_at DESC" if sort == "top"
             else "c.created_at DESC")
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _COMMENT_SELECT
            + " WHERE c.video_id = ? AND c.parent_id IS NULL"
            + f" ORDER BY {order} LIMIT ? OFFSET ?",
            (video_id, limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_top_comments(video_id: str) -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM comments WHERE video_id = ? AND parent_id IS NULL",
            (video_id,))
        return (await cursor.fetchone())[0]


async def list_replies(root_id: str, limit: int, offset: int) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _COMMENT_SELECT
            + " WHERE c.root_id = ? ORDER BY c.created_at ASC LIMIT ? OFFSET ?",
            (root_id, limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_replies(root_id: str) -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM comments WHERE root_id = ? AND status = 'active'",
            (root_id,))
        return (await cursor.fetchone())[0]


async def reply_counts(root_ids: list[str]) -> dict[str, int]:
    if not root_ids:
        return {}
    placeholders = ",".join("?" * len(root_ids))
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""SELECT root_id, COUNT(*) AS n FROM comments
                WHERE root_id IN ({placeholders}) AND status = 'active'
                GROUP BY root_id""",
            tuple(root_ids),
        )
        return {r["root_id"]: r["n"] for r in await cursor.fetchall()}


async def soft_delete_comment(comment_id: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE comments SET status='deleted', body='', updated_at=? "
            "WHERE id = ?",
            (time.time(), comment_id),
        )
        await db.commit()


async def viewer_votes(user_id: str, comment_ids: list[str]) -> dict[str, int]:
    if not comment_ids:
        return {}
    placeholders = ",".join("?" * len(comment_ids))
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""SELECT comment_id, value FROM comment_votes
                WHERE user_id = ? AND comment_id IN ({placeholders})""",
            (user_id, *comment_ids),
        )
        return {r["comment_id"]: r["value"] for r in await cursor.fetchall()}


async def apply_vote(user_id: str, comment_id: str, value: int) -> dict:
    """Set the viewer's vote to value (+1/-1/0) and refresh denormalized counts.

    Runs entirely in one connection (single writer => no cross-process race).
    Returns {like_count, dislike_count, score}.
    """
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        cur = await db.execute(
            "SELECT value FROM comment_votes WHERE user_id = ? AND comment_id = ?",
            (user_id, comment_id),
        )
        row = await cur.fetchone()
        old = row[0] if row else None
        if old != value:
            like_delta = dislike_delta = 0
            if value == 1:
                like_delta += 1
            elif value == -1:
                dislike_delta += 1
            if old == 1:
                like_delta -= 1
            elif old == -1:
                dislike_delta -= 1

            if value == 0:
                await db.execute(
                    "DELETE FROM comment_votes WHERE user_id = ? AND comment_id = ?",
                    (user_id, comment_id),
                )
            elif old is None:
                await db.execute(
                    """INSERT INTO comment_votes
                       (user_id, comment_id, value, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, comment_id, value, now, now),
                )
            else:
                await db.execute(
                    """UPDATE comment_votes SET value = ?, updated_at = ?
                       WHERE user_id = ? AND comment_id = ?""",
                    (value, now, user_id, comment_id),
                )
            await db.execute(
                """UPDATE comments
                   SET like_count = like_count + ?,
                       dislike_count = dislike_count + ?,
                       score = (like_count + ?) - (dislike_count + ?),
                       updated_at = ?
                   WHERE id = ?""",
                (like_delta, dislike_delta, like_delta, dislike_delta, now,
                 comment_id),
            )
        cur = await db.execute(
            "SELECT like_count, dislike_count, score FROM comments WHERE id = ?",
            (comment_id,),
        )
        r = await cur.fetchone()
        await db.commit()
        return {"like_count": r[0], "dislike_count": r[1], "score": r[2]}
```

- [ ] **Step 3: 语法检查**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/database.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

- [ ] **Step 4: 行为验证**

创建临时脚本 `youtube-system/_verify_comments_db.py`：

```python
"""Temp check: comments/comment_votes DDL + data-access + apply_vote math."""
import asyncio
import os
import tempfile

from app import database
from app.config import config


async def main():
    tmp = tempfile.mkdtemp()
    config.db_path = os.path.join(tmp, "t.db")
    await database.init_db()

    # seed a user + video the FKs point at
    await database.insert_user("u1", "alice", "a@t.local", "h", "user")
    await database.insert_user("u2", "bob", "b@t.local", "h", "moderator")
    await database.insert_video("v" * 12, "T", "", "orig", uploader_id="u1")

    # top-level + two replies + one reply-to-reply flattening
    await database.insert_comment("c1", "v" * 12, "u1", "top", None, None)
    await database.insert_comment("c2", "v" * 12, "u2", "r1", "c1", "c1")
    await database.insert_comment("c3", "v" * 12, "u1", "r2", "c2", "c1")  # reuses c1 root

    top = await database.list_top_comments("v" * 12, "top", 20, 0)
    assert [c["id"] for c in top] == ["c1"], top
    assert top[0]["author_username"] == "alice", top[0]
    assert await database.count_top_comments("v" * 12) == 1

    reps = await database.list_replies("c1", 20, 0)
    assert [c["id"] for c in reps] == ["c2", "c3"], reps  # created_at ASC
    assert await database.count_replies("c1") == 2
    assert (await database.reply_counts(["c1"])) == {"c1": 2}

    # voting transitions and counter math
    r = await database.apply_vote("u1", "c1", 1)
    assert (r["like_count"], r["dislike_count"], r["score"]) == (1, 0, 1), r
    r = await database.apply_vote("u1", "c1", 1)   # idempotent re-like
    assert r == {"like_count": 1, "dislike_count": 0, "score": 1}, r
    r = await database.apply_vote("u1", "c1", -1)  # switch like -> dislike
    assert (r["like_count"], r["dislike_count"], r["score"]) == (0, 1, -1), r
    r = await database.apply_vote("u2", "c1", 1)
    assert (r["like_count"], r["dislike_count"], r["score"]) == (1, 1, 0), r
    r = await database.apply_vote("u1", "c1", 0)   # cancel
    assert (r["like_count"], r["dislike_count"], r["score"]) == (1, 0, 1), r

    votes = await database.viewer_votes("u2", ["c1", "c2"])
    assert votes == {"c1": 1}, votes

    await database.soft_delete_comment("c2")
    gone = await database.get_comment("c2")
    assert gone["status"] == "deleted" and gone["body"] == "", gone
    assert await database.count_replies("c1") == 1  # deleted reply not counted

    print("COMMENTS_DB_OK")


asyncio.run(main())
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_comments_db.py
```

Expected: `COMMENTS_DB_OK`

- [ ] **Step 5: 清理临时文件**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item _verify_comments_db.py -Force -ErrorAction SilentlyContinue; Write-Output "cleaned"
```

Expected: `cleaned`

- [ ] **Step 6: 提交**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes; git add youtube-system/app/database.py; git commit -m 'feat: add youtube-comments tables and data access layer' *> $null; Write-Output exit=$LASTEXITCODE
```

Expected: `exit=0`

---

## Task 2: `schemas.py` + `service.py`——建评论/回复 + 列表读路径

**Files:**
- Create: `youtube-system/app/comments/__init__.py`
- Create: `youtube-system/app/comments/schemas.py`
- Create: `youtube-system/app/comments/service.py`

- [ ] **Step 1: 包声明**

`youtube-system/app/comments/__init__.py`（空文件会被写入工具拒绝，必须带 docstring）：

```python
"""Comments + likes subpackage (spec 3): schemas/service/router over the comments tables."""
```

- [ ] **Step 2: 写 schemas.py**

```python
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
```

- [ ] **Step 3: 写 service.py（含投影 + 建评论 + 读路径；投票/删除在 Task 3 补）**

```python
"""Comments + likes business logic (spec 5).

Reaches the database only through app.database; raises domain exceptions that
router.py maps to HTTP codes. Auth primitives are reused from app.auth, so role
constants live in exactly one place.
"""
import secrets

from app import database
from app.auth.security import ROLE_LEVEL
from app.comments import schemas

_MODERATOR_LEVEL = ROLE_LEVEL["moderator"]


class NotFoundError(Exception):
    """404 - video or comment does not exist."""


class ValidationError(Exception):
    """400 - empty/long content, cross-video reply, vote/reply on deleted."""


class PermissionDenied(Exception):
    """403 - neither the author nor moderator+."""


def _out(row: dict, reply_count: int = 0, my_vote: int = 0) -> dict:
    deleted = row["status"] == "deleted"
    author = ({"id": None, "username": "deleted"} if deleted
              else {"id": row["author_id"], "username": row.get("author_username")})
    return {
        "id": row["id"], "video_id": row["video_id"], "author": author,
        "content": schemas.DELETED_PLACEHOLDER if deleted else row["body"],
        "status": row["status"],
        "parent_id": row["parent_id"], "root_id": row["root_id"],
        "like_count": row["like_count"], "dislike_count": row["dislike_count"],
        "score": row["score"], "reply_count": reply_count,
        "my_vote": my_vote, "created_at": row["created_at"],
    }


async def create_comment(video_id: str, author_id: str, content: str,
                         reply_to: str | None = None) -> dict:
    body = (content or "").strip()
    if not body or len(body) > schemas.CONTENT_MAX:
        raise ValidationError("content must be 1-1000 characters")
    if await database.get_video(video_id) is None:
        raise NotFoundError("video not found")

    parent_id = root_id = None
    if reply_to:
        parent = await database.get_comment(reply_to)
        if parent is None:
            raise NotFoundError("comment not found")
        if parent["video_id"] != video_id:
            raise ValidationError("reply_to belongs to a different video")
        if parent["status"] != "active":
            raise ValidationError("cannot reply to a deleted comment")
        parent_id = parent["id"]
        root_id = parent["root_id"] or parent["id"]

    comment_id = secrets.token_hex(12)
    await database.insert_comment(
        comment_id, video_id, author_id, body, parent_id, root_id)
    row = await database.get_comment(comment_id)
    return _out(row, reply_count=0, my_vote=0)


async def list_comments(video_id: str, sort: str, limit: int, offset: int,
                        viewer) -> dict:
    if await database.get_video(video_id) is None:
        raise NotFoundError("video not found")
    order = sort if sort in ("top", "new") else "top"
    rows = await database.list_top_comments(video_id, order, limit, offset)
    total = await database.count_top_comments(video_id)
    ids = [r["id"] for r in rows]
    counts = await database.reply_counts(ids)
    votes = await database.viewer_votes(viewer.id, ids) if viewer else {}
    out = [_out(r, reply_count=counts.get(r["id"], 0),
                my_vote=votes.get(r["id"], 0)) for r in rows]
    return {"comments": out, "total": total,
            "has_more": offset + len(rows) < total}


async def list_replies(comment_id: str, limit: int, offset: int, viewer) -> dict:
    root = await database.get_comment(comment_id)
    if root is None or root["parent_id"] is not None:
        raise NotFoundError("top-level comment not found")
    rows = await database.list_replies(comment_id, limit, offset)
    total = await database.count_replies(comment_id)
    ids = [r["id"] for r in rows]
    votes = await database.viewer_votes(viewer.id, ids) if viewer else {}
    out = [_out(r, reply_count=0, my_vote=votes.get(r["id"], 0)) for r in rows]
    return {"comments": out, "total": total,
            "has_more": offset + len(rows) < total}
```

- [ ] **Step 4: 语法检查**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/comments/__init__.py app/comments/schemas.py app/comments/service.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

- [ ] **Step 5: 行为验证**

创建 `youtube-system/_verify_comments_read.py`：

```python
"""Temp check: create/list read path incl. reply flattening, my_vote, sorting."""
import asyncio
import os
import tempfile
from types import SimpleNamespace

from app import database
from app.auth import security
from app.comments import service
from app.config import config


async def main():
    config.db_path = os.path.join(tempfile.mkdtemp(), "t.db")
    await database.init_db()
    await database.insert_user("u1", "alice", "a@t.local", "h", "user")
    await database.insert_user("u2", "bob", "b@t.local", "h", "user")
    await database.insert_video("vid12345678", "T", "", "orig", uploader_id="u1")

    # top-level
    t1 = await service.create_comment("vid12345678", "u1", "  hello world  ")
    assert t1["content"] == "hello world", t1  # stripped
    assert t1["status"] == "active" and t1["author"]["username"] == "alice", t1
    assert t1["parent_id"] is None and t1["root_id"] is None, t1

    # reply to top-level
    r1 = await service.create_comment("vid12345678", "u2", "nice", reply_to=t1["id"])
    assert r1["parent_id"] == t1["id"] and r1["root_id"] == t1["id"], r1
    # reply to a reply -> flattens to same root, parent is the reply
    r2 = await service.create_comment("vid12345678", "u1", "agree", reply_to=r1["id"])
    assert r2["parent_id"] == r1["id"] and r2["root_id"] == t1["id"], r2

    # validation: empty content
    try:
        await service.create_comment("vid12345678", "u1", "   ")
        raise AssertionError("empty content should fail")
    except service.ValidationError:
        pass
    # missing video -> 404
    try:
        await service.create_comment("doesnotexist", "u1", "hi")
        raise AssertionError("missing video should 404")
    except service.NotFoundError:
        pass
    # cross-video reply rejected
    await database.insert_video("vid99999999", "T2", "", "orig2", uploader_id="u1")
    try:
        await service.create_comment("vid99999999", "u1", "x", reply_to=t1["id"])
        raise AssertionError("cross-video reply should fail")
    except service.ValidationError:
        pass

    # top-level list with reply_count
    res = await service.list_comments("vid12345678", "top", 20, 0, None)
    assert res["total"] == 1 and res["has_more"] is False, res
    assert res["comments"][0]["reply_count"] == 2, res["comments"][0]

    # replies chronological
    reps = await service.list_replies(t1["id"], 20, 0, None)
    assert [c["content"] for c in reps["comments"]] == ["nice", "agree"], reps
    # asking replies of a non-top comment -> 404
    try:
        await service.list_replies(r1["id"], 20, 0, None)
        raise AssertionError("replies of a reply should 404")
    except service.NotFoundError:
        pass

    # my_vote annotation (bob liked t1)
    await database.apply_vote("u2", t1["id"], 1)
    anon = await service.list_comments("vid12345678", "top", 20, 0, None)
    assert anon["comments"][0]["my_vote"] == 0, anon
    as_bob = await service.list_comments(
        "vid12345678", "top", 20, 0, SimpleNamespace(id="u2"))
    assert as_bob["comments"][0]["my_vote"] == 1, as_bob
    assert as_bob["comments"][0]["like_count"] == 1, as_bob

    print("COMMENTS_READ_OK")


asyncio.run(main())
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_comments_read.py
```

Expected: `COMMENTS_READ_OK`

- [ ] **Step 6: 清理 + 提交**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item _verify_comments_read.py -Force -ErrorAction SilentlyContinue; Set-Location D:\StudyProjects\system-design-notes; git add youtube-system/app/comments/__init__.py youtube-system/app/comments/schemas.py youtube-system/app/comments/service.py; git commit -m 'feat: add youtube-comments create and list read path' *> $null; Write-Output exit=$LASTEXITCODE
```

Expected: `exit=0`

---

## Task 3: service.py 投票 + 软删除（权限判定）

**Files:**
- Modify: `youtube-system/app/comments/service.py`

- [ ] **Step 1: 追加 `vote` 与 `delete_comment` 到 `service.py` 末尾**

```python
async def vote(comment_id: str, user_id: str, value: int) -> dict:
    if value not in (-1, 0, 1):
        raise ValidationError("value must be -1, 0 or 1")
    row = await database.get_comment(comment_id)
    if row is None:
        raise NotFoundError("comment not found")
    if row["status"] != "active":
        raise ValidationError("cannot vote on a deleted comment")
    counters = await database.apply_vote(user_id, comment_id, value)
    return {**counters, "my_vote": value}


async def delete_comment(comment_id: str, actor_id: str, actor_role: str) -> None:
    row = await database.get_comment(comment_id)
    if row is None:
        raise NotFoundError("comment not found")
    is_author = row["author_id"] == actor_id
    is_staff = ROLE_LEVEL.get(actor_role, 0) >= _MODERATOR_LEVEL
    if not (is_author or is_staff):
        raise PermissionDenied("not allowed to delete this comment")
    if row["status"] == "active":
        await database.soft_delete_comment(comment_id)
```

- [ ] **Step 2: 语法检查**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/comments/service.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

- [ ] **Step 3: 行为验证**

创建 `youtube-system/_verify_comments_vote.py`：

```python
"""Temp check: vote transitions + soft-delete permission matrix."""
import asyncio
import os
import tempfile

from app import database
from app.comments import service
from app.config import config


async def main():
    config.db_path = os.path.join(tempfile.mkdtemp(), "t.db")
    await database.init_db()
    await database.insert_user("u1", "alice", "a@t.local", "h", "user")
    await database.insert_user("u2", "bob", "b@t.local", "h", "user")
    await database.insert_user("u3", "mod", "m@t.local", "h", "moderator")
    await database.insert_video("vid12345678", "T", "", "orig", uploader_id="u1")
    c = await service.create_comment("vid12345678", "u1", "target")
    cid = c["id"]

    # vote add / switch / cancel returns live counters + my_vote
    r = await service.vote(cid, "u1", 1)
    assert r == {"like_count": 1, "dislike_count": 0, "score": 1, "my_vote": 1}, r
    r = await service.vote(cid, "u2", -1)
    assert (r["like_count"], r["dislike_count"], r["score"]) == (1, 1, 0), r
    r = await service.vote(cid, "u1", -1)  # alice switches to dislike
    assert (r["like_count"], r["dislike_count"], r["score"]) == (0, 2, -2), r
    r = await service.vote(cid, "u1", 0)   # cancel (u1's dislike removed; u2's remains)
    assert (r["like_count"], r["dislike_count"], r["my_vote"]) == (0, 1, 0), r

    # invalid value and voting a deleted comment
    try:
        await service.vote(cid, "u1", 5)
        raise AssertionError("bad value")
    except service.ValidationError:
        pass

    # delete permission matrix
    try:
        await service.delete_comment(cid, "u2", "user")   # non-author, non-staff
        raise AssertionError("bob must not delete alice comment")
    except service.PermissionDenied:
        pass
    await service.delete_comment(cid, "u1", "user")        # author ok
    got = await database.get_comment(cid)
    assert got["status"] == "deleted" and got["body"] == "", got
    # vote on deleted now rejected
    try:
        await service.vote(cid, "u2", 1)
        raise AssertionError("vote on deleted must fail")
    except service.ValidationError:
        pass
    # moderator can delete someone else's comment
    c2 = await service.create_comment("vid12345678", "u1", "another")
    await service.delete_comment(c2["id"], "u3", "moderator")
    assert (await database.get_comment(c2["id"]))["status"] == "deleted"
    # re-delete is idempotent (no error)
    await service.delete_comment(c2["id"], "u1", "user")

    print("COMMENTS_VOTE_OK")


asyncio.run(main())
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_comments_vote.py
```

Expected: `COMMENTS_VOTE_OK`

- [ ] **Step 4: 清理 + 提交**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item _verify_comments_vote.py -Force -ErrorAction SilentlyContinue; Set-Location D:\StudyProjects\system-design-notes; git add youtube-system/app/comments/service.py; git commit -m 'feat: add youtube-comments vote and soft-delete with permission check' *> $null; Write-Output exit=$LASTEXITCODE
```

Expected: `exit=0`

---


## Task 4: `router.py` + `server.py` 接线

**Files:**
- Create: `youtube-system/app/comments/router.py`
- Modify: `youtube-system/app/server.py`

- [ ] **Step 1: 写 router.py**

```python
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
```

- [ ] **Step 2: 在 `server.py` 接线**

在 `app/server.py` 的 import 段，`from app.auth.router import router as auth_router` 之后追加一行：

```python
from app.comments.router import router as comments_router
```

在 `app.include_router(auth_router)` 之后追加一行：

```python
app.include_router(comments_router)
```

- [ ] **Step 3: 语法检查**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/comments/router.py app/server.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

- [ ] **Step 4: 路由表验证**

创建 `youtube-system/_verify_comment_routes.py`：

```python
"""Temp check: comments endpoints are registered on the app."""
from app.server import app

expected = {
    ("GET", "/api/videos/{video_id}/comments"),
    ("GET", "/api/comments/{comment_id}/replies"),
    ("POST", "/api/videos/{video_id}/comments"),
    ("DELETE", "/api/comments/{comment_id}"),
    ("PUT", "/api/comments/{comment_id}/vote"),
}
found = set()
for r in app.routes:
    methods = getattr(r, "methods", None)
    path = getattr(r, "path", None)
    if not methods or not path:
        continue
    for m in methods:
        if m not in ("HEAD", "OPTIONS"):
            found.add((m, path))

missing = expected - found
assert not missing, f"missing routes: {missing}"
print("COMMENT_ROUTES_OK")
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_comment_routes.py
```

Expected: `COMMENT_ROUTES_OK`

- [ ] **Step 5: 清理 + 提交**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item _verify_comment_routes.py -Force -ErrorAction SilentlyContinue; Set-Location D:\StudyProjects\system-design-notes; git add youtube-system/app/comments/router.py youtube-system/app/server.py; git commit -m 'feat: wire youtube-comments router into the api server' *> $null; Write-Output exit=$LASTEXITCODE
```

Expected: `exit=0`

---

## Task 5: 后端 e2e（对运行中的容器）

**Files:**
- 无源码改动（仅部署验证）。前置：Task 1–4 已提交。

- [ ] **Step 1: 重建并启动 api-server**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose up -d --build api-server; Write-Output exit=$LASTEXITCODE
```

后台执行 + `GetTerminalOutput` 轮询到 `exit=0`。

- [ ] **Step 2: 等待健康**

Run:

```powershell
Start-Sleep -Seconds 5; Invoke-RestMethod http://localhost:8000/api/health | ConvertTo-Json -Compress
```

Expected: `{"status":"ok"}`

- [ ] **Step 3: 跑 e2e**

创建 `youtube-system/_e2e_comments.py`：

```python
"""Temp e2e over HTTP for comments. Requires >=1 existing video in the stack."""
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, (json.loads(raw) if raw else None)
        except json.JSONDecodeError:
            return e.code, {"detail": raw.decode(errors="replace")}


suffix = str(int(time.time()))
user = f"cmt_{suffix}"
email = f"{user}@t.local"
call("POST", "/api/auth/register",
     {"username": user, "email": email, "password": "Passw0rd!"})
s, lg = call("POST", "/api/auth/login",
             {"email": email, "password": "Passw0rd!"})
assert s == 200, (s, lg)
tok = lg["access_token"]

s, vids = call("GET", "/api/videos")
assert s == 200 and vids["videos"], ("no videos for e2e", s, vids)
video_id = vids["videos"][0]["id"]

# anonymous create -> 401
assert call("POST", f"/api/videos/{video_id}/comments", {"content": "x"})[0] == 401
# authed create top-level
s, c1 = call("POST", f"/api/videos/{video_id}/comments",
             {"content": "first e2e"}, token=tok)
assert s == 201 and c1["content"] == "first e2e", (s, c1)
cid = c1["id"]
# reply (root_id == parent)
s, r1 = call("POST", f"/api/videos/{video_id}/comments",
             {"content": "reply", "reply_to": cid}, token=tok)
assert s == 201 and r1["root_id"] == cid and r1["parent_id"] == cid, (s, r1)
# vote up, switch to dislike
s, v = call("PUT", f"/api/comments/{cid}/vote", {"value": 1}, token=tok)
assert s == 200 and v["like_count"] == 1 and v["my_vote"] == 1, (s, v)
s, v = call("PUT", f"/api/comments/{cid}/vote", {"value": -1}, token=tok)
assert s == 200 and v["like_count"] == 0 and v["dislike_count"] == 1, (s, v)
# invalid value -> 422
assert call("PUT", f"/api/comments/{cid}/vote", {"value": 5}, token=tok)[0] == 422
# anonymous list: sees comment, my_vote 0
s, lst = call("GET", f"/api/videos/{video_id}/comments?sort=new&limit=50")
assert s == 200 and any(c["id"] == cid for c in lst["comments"]), (s, lst)
mine = next(c for c in lst["comments"] if c["id"] == cid)
assert mine["reply_count"] >= 1 and mine["my_vote"] == 0, mine
# authed list: my_vote reflects own vote
s, lst2 = call("GET", f"/api/videos/{video_id}/comments?sort=new&limit=50", token=tok)
assert next(c for c in lst2["comments"] if c["id"] == cid)["my_vote"] == -1
# replies list
s, reps = call("GET", f"/api/comments/{cid}/replies")
assert s == 200 and any(r["id"] == r1["id"] for r in reps["comments"]), (s, reps)
# other user cannot delete -> 403
call("POST", "/api/auth/register",
     {"username": f"x{user}", "email": f"x{email}", "password": "Passw0rd!"})
s, lg2 = call("POST", "/api/auth/login",
              {"email": f"x{email}", "password": "Passw0rd!"})
assert call("DELETE", f"/api/comments/{cid}", token=lg2["access_token"])[0] == 403
# author deletes -> 204
assert call("DELETE", f"/api/comments/{cid}", token=tok)[0] == 204
# deleted placeholder in list
s, lst3 = call("GET", f"/api/videos/{video_id}/comments?sort=new&limit=50")
d = next((c for c in lst3["comments"] if c["id"] == cid), None)
assert d and d["status"] == "deleted" and d["content"] == "This comment was deleted.", d

print("COMMENTS_E2E_OK")
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _e2e_comments.py
```

Expected: `COMMENTS_E2E_OK`

- [ ] **Step 4: 清理**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item _e2e_comments.py -Force -ErrorAction SilentlyContinue; Write-Output cleaned
```

Expected: `cleaned`

---

## Task 6: 前端 `api.js`——评论/投票函数

**Files:**
- Modify: `youtube-system/frontend/src/api.js`

- [ ] **Step 1: 在 `api.js` 末尾追加**

```js
// ---- comments & votes ----
export function listComments(videoId, { sort = 'top', limit = 20, offset = 0 } = {}) {
  return http.get(`/api/videos/${videoId}/comments`, { params: { sort, limit, offset } })
}

export function listReplies(commentId, { limit = 20, offset = 0 } = {}) {
  return http.get(`/api/comments/${commentId}/replies`, { params: { limit, offset } })
}

export function createComment(videoId, content, replyTo = null) {
  return http.post(`/api/videos/${videoId}/comments`, { content, reply_to: replyTo })
}

export function deleteComment(commentId) {
  return http.delete(`/api/comments/${commentId}`)
}

export function voteComment(commentId, value) {
  return http.put(`/api/comments/${commentId}/vote`, { value })
}
```

- [ ] **Step 2: 构建验证**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system\frontend; npm run build *> $null; Write-Output "build_exit=$LASTEXITCODE"
```

Expected: `build_exit=0`

- [ ] **Step 3: 提交**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes; git add youtube-system/frontend/src/api.js; git commit -m 'feat: add youtube-comments api functions to the frontend' *> $null; Write-Output exit=$LASTEXITCODE
```

Expected: `exit=0`

---

## Task 7: 前端评论组件 + WatchView + 样式

**Files:**
- Create: `youtube-system/frontend/src/components/CommentItem.vue`
- Create: `youtube-system/frontend/src/components/Comments.vue`
- Modify: `youtube-system/frontend/src/views/WatchView.vue`
- Modify: `youtube-system/frontend/src/style.css`

- [ ] **Step 1: 写 CommentItem.vue**

（`<script setup>` 组件可用「文件名即组件名」在自身模板里递归引用 `<CommentItem>`，无需 import。回复项 `root_id` 非空即 `isReply`，据此隐藏其回复/展开控件，保持 1 级 UI。）

```vue
<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  createComment, deleteComment, extractError, listReplies, voteComment,
} from '../api'
import { authState, hasRole } from '../auth'

const props = defineProps({ comment: { type: Object, required: true } })
const emit = defineEmits(['deleted'])
const route = useRoute()
const router = useRouter()

// The parent holds these objects in a reactive array, so mutating fields here
// updates the list in place (vote counts, reply_count) without re-fetching.
const c = props.comment
const isReply = computed(() => !!c.root_id)
const canDelete = computed(() =>
  !!authState.user && (authState.user.id === c.author.id || hasRole('moderator')))

const voteError = ref('')
const showReplies = ref(false)
const replies = ref([])
const repliesTotal = ref(0)
const repliesLoaded = ref(false)
const replyLoading = ref(false)
const replyOpen = ref(false)
const replyDraft = ref('')

function fmtDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : ''
}

function gotoLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

async function vote(value) {
  if (!authState.user) { gotoLogin(); return }
  voteError.value = ''
  try {
    const { data } = await voteComment(c.id, value)
    c.like_count = data.like_count
    c.dislike_count = data.dislike_count
    c.score = data.score
    c.my_vote = data.my_vote
  } catch (e) {
    voteError.value = extractError(e, 'Vote failed')
  }
}

async function loadReplies() {
  replyLoading.value = true
  try {
    const { data } = await listReplies(c.id, { limit: 50, offset: 0 })
    replies.value = data.comments
    repliesTotal.value = data.total
    repliesLoaded.value = true
  } catch (e) {
    voteError.value = extractError(e, 'Could not load replies')
  } finally {
    replyLoading.value = false
  }
}

function toggleReplies() {
  showReplies.value = !showReplies.value
  if (showReplies.value && !repliesLoaded.value) loadReplies()
}

async function submitReply() {
  if (!authState.user) { gotoLogin(); return }
  const text = replyDraft.value.trim()
  if (!text) return
  try {
    const { data } = await createComment(c.video_id, text, c.id)
    replies.value.push(data)
    repliesTotal.value += 1
    c.reply_count += 1
    replyDraft.value = ''
    showReplies.value = true
    repliesLoaded.value = true
  } catch (e) {
    voteError.value = extractError(e, 'Could not reply')
  }
}

async function remove() {
  try {
    await deleteComment(c.id)
    emit('deleted', c.id)
  } catch (e) {
    voteError.value = extractError(e, 'Could not delete')
  }
}
</script>

<template>
  <div class="comment">
    <div class="comment-head">
      <span class="comment-author">{{ c.author.username }}</span>
      <span class="comment-date">{{ fmtDate(c.created_at) }}</span>
    </div>
    <p class="comment-body" :class="{ deleted: c.status === 'deleted' }">{{ c.content }}</p>

    <div v-if="voteError" class="error-box">{{ voteError }}</div>

    <div class="comment-actions">
      <button class="vote" :class="{ on: c.my_vote === 1 }"
              :disabled="c.status === 'deleted'" @click="vote(1)">
        👍 {{ c.like_count }}
      </button>
      <button class="vote" :class="{ on: c.my_vote === -1 }"
              :disabled="c.status === 'deleted'" @click="vote(-1)">
        👎 {{ c.dislike_count }}
      </button>
      <template v-if="c.status === 'active' && !isReply">
        <button class="link" @click="replyOpen = !replyOpen">Reply</button>
        <button v-if="c.reply_count || showReplies" class="link" @click="toggleReplies">
          {{ showReplies ? 'Hide' : 'View' }} {{ c.reply_count || repliesTotal }}
          {{ (c.reply_count || repliesTotal) === 1 ? 'reply' : 'replies' }}
        </button>
      </template>
      <button v-if="canDelete" class="link danger" @click="remove">Delete</button>
    </div>

    <div v-if="replyOpen && !isReply" class="comment-form reply-form">
      <textarea v-model="replyDraft" rows="2"
                :placeholder="authState.user ? 'Write a reply…' : 'Sign in to reply'"></textarea>
      <div class="comment-form-actions">
        <button class="btn secondary" @click="replyOpen = false">Cancel</button>
        <button class="btn" :disabled="!replyDraft.trim()" @click="submitReply">Reply</button>
      </div>
    </div>

    <div v-if="showReplies" class="replies">
      <p v-if="replyLoading" class="comments-empty">Loading replies…</p>
      <CommentItem v-for="r in replies" :key="r.id" :comment="r" />
      <p v-if="!replyLoading && repliesLoaded && !replies.length" class="comments-empty">
        No replies yet.
      </p>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 写 Comments.vue**

```vue
<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createComment, extractError, listComments } from '../api'
import { authState } from '../auth'
import CommentItem from './CommentItem.vue'

const props = defineProps({ videoId: { type: String, required: true } })
const route = useRoute()
const router = useRouter()

const PAGE = 20
const comments = ref([])
const total = ref(0)
const sort = ref('top')
const error = ref('')
const loading = ref(false)
const draft = ref('')
const submitting = ref(false)

const canLoadMore = () => comments.value.length < total.value

async function load(reset = false) {
  loading.value = true
  error.value = ''
  try {
    const offset = reset ? 0 : comments.value.length
    const { data } = await listComments(
      props.videoId, { sort: sort.value, limit: PAGE, offset })
    total.value = data.total
    comments.value = reset ? data.comments : comments.value.concat(data.comments)
  } catch (e) {
    error.value = extractError(e, 'Could not load comments')
  } finally {
    loading.value = false
  }
}

function changeSort(s) {
  if (sort.value === s) return
  sort.value = s
  load(true)
}

function gotoLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

async function submit() {
  if (!authState.user) { gotoLogin(); return }
  const text = draft.value.trim()
  if (!text) return
  submitting.value = true
  error.value = ''
  try {
    const { data } = await createComment(props.videoId, text)
    comments.value.unshift(data)
    total.value += 1
    draft.value = ''
  } catch (e) {
    error.value = extractError(e, 'Could not post comment')
  } finally {
    submitting.value = false
  }
}

function onDeleted(id) {
  comments.value = comments.value.filter((c) => c.id !== id)
  total.value = Math.max(0, total.value - 1)
}

onMounted(() => load(true))
watch(() => props.videoId, () => load(true))
</script>

<template>
  <section class="comments">
    <h3>Comments <small v-if="total">({{ total }})</small></h3>

    <div class="comment-form">
      <textarea
        v-model="draft"
        rows="2"
        :placeholder="authState.user ? 'Add a comment…' : 'Sign in to comment'"
        @focus="!authState.user && gotoLogin()"
      ></textarea>
      <div class="comment-form-actions">
        <button class="btn" :disabled="submitting || !authState.user" @click="submit">
          {{ authState.user ? (submitting ? 'Posting…' : 'Comment') : 'Sign in' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div class="comment-sort">
      <button :class="{ active: sort === 'top' }" @click="changeSort('top')">Top</button>
      <button :class="{ active: sort === 'new' }" @click="changeSort('new')">Newest</button>
    </div>

    <p v-if="!comments.length && !loading" class="comments-empty">No comments yet.</p>

    <CommentItem v-for="c in comments" :key="c.id" :comment="c" @deleted="onDeleted" />

    <button
      v-if="canLoadMore()"
      class="btn secondary"
      style="margin-top: 12px"
      :disabled="loading"
      @click="load()"
    >
      {{ loading ? 'Loading…' : `Load more (${comments.length}/${total})` }}
    </button>
  </section>
</template>
```

- [ ] **Step 3: WatchView.vue 挂载 Comments**

在 `youtube-system/frontend/src/views/WatchView.vue` 的 `<script setup>` 中，`import Hls from 'hls.js'` 之后追加：

```js
import Comments from '../components/Comments.vue'
```

在模板中，把画质选择块的收尾与其后左列的闭合：

```html
        <div v-if="levels.length" style="margin-top: 12px">
          Quality:
          <select @change="setLevel(+$event.target.value)">
            <option value="-1" :selected="currentLevel === -1">Auto</option>
            <option
              v-for="l in levels"
              :key="l.i"
              :value="l.i"
              :selected="currentLevel === l.i"
            >
              {{ l.height }}p
            </option>
          </select>
        </div>
      </div>
```

替换为（在 `</div>` 关闭左列之前插入 `<Comments>`）：

```html
        <div v-if="levels.length" style="margin-top: 12px">
          Quality:
          <select @change="setLevel(+$event.target.value)">
            <option value="-1" :selected="currentLevel === -1">Auto</option>
            <option
              v-for="l in levels"
              :key="l.i"
              :value="l.i"
              :selected="currentLevel === l.i"
            >
              {{ l.height }}p
            </option>
          </select>
        </div>

        <Comments :video-id="route.params.id" />
      </div>
```

- [ ] **Step 4: 追加评论样式**

在 `youtube-system/frontend/src/style.css` 末尾追加：

```css

/* ---- Comments & votes ---- */
.comments { margin-top: 28px; border-top: 1px solid var(--border); padding-top: 20px; }
.comments h3 { margin: 0 0 16px; font-size: 18px; }
.comments h3 small { color: var(--text-dim); font-weight: 400; }

.comment-form { margin-bottom: 16px; }
.comment-form textarea {
  width: 100%; padding: 10px 12px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--bg-card); color: var(--text);
  font-size: 14px; resize: vertical; min-height: 60px;
}
.comment-form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.reply-form { margin: 10px 0; }

.comment-sort { display: flex; gap: 16px; margin-bottom: 14px; }
.comment-sort button {
  background: none; border: none; color: var(--text-dim);
  font-size: 14px; font-weight: 600; cursor: pointer; padding: 4px 0;
}
.comment-sort button.active { color: var(--text); border-bottom: 2px solid var(--accent); }

.comment { padding: 12px 0; border-bottom: 1px solid var(--border); }
.comment-head { display: flex; align-items: baseline; gap: 8px; }
.comment-author { font-size: 13px; font-weight: 600; }
.comment-date { font-size: 12px; color: var(--text-dim); }
.comment-body { margin: 6px 0; font-size: 14px; line-height: 1.4; white-space: pre-wrap; }
.comment-body.deleted { color: var(--text-dim); font-style: italic; }

.comment-actions { display: flex; align-items: center; gap: 14px; }
.vote { background: none; border: none; color: var(--text-dim); font-size: 13px; cursor: pointer; }
.vote:hover { color: var(--text); }
.vote.on { color: var(--accent); font-weight: 700; }
.vote:disabled { opacity: 0.5; cursor: not-allowed; }
.link { background: none; border: none; color: var(--text-dim); font-size: 13px; cursor: pointer; padding: 0; }
.link:hover { color: var(--text); }
.link.danger:hover { color: var(--accent); }

.replies { margin-left: 24px; border-left: 2px solid var(--border); padding-left: 12px; }
.comments-empty { color: var(--text-dim); font-size: 13px; padding: 8px 0; }
```

- [ ] **Step 5: 构建验证**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system\frontend; npm run build *> $null; Write-Output "build_exit=$LASTEXITCODE"
```

Expected: `build_exit=0`

- [ ] **Step 6: 部署 frontend**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose up -d --build frontend *> $null; Write-Output "deploy_exit=$LASTEXITCODE"
```

Expected: `deploy_exit=0`

- [ ] **Step 7: 提交**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes; git add youtube-system/frontend/src/components/CommentItem.vue youtube-system/frontend/src/components/Comments.vue youtube-system/frontend/src/views/WatchView.vue youtube-system/frontend/src/style.css; git commit -m 'feat: add comments and votes UI to the youtube watch page' *> $null; Write-Output exit=$LASTEXITCODE
```

Expected: `exit=0`

---

## Task 8: 全栈验证 + README

**Files:**
- Modify: `youtube-system/README.md`

- [ ] **Step 1: 全栈重建并确认 5 容器健康**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose up -d --build; docker compose ps
```

Expected: redis(healthy)/api-server/transcoder-worker/cdn/frontend 全部 `Up`。

- [ ] **Step 2: 端到端手测清单（浏览器）**

1. **匿名**打开任一 ready 视频 → Watch 页下方出现 Comments 区，能读到已有评论，赞/踩计数显示但 `my_vote` 无高亮
2. 匿名点赞/踩 或 在发表框输入 → 跳 `/login?redirect=/watch/...`，登录后**自动回到该视频**
3. 登录普通账号 → 发一条评论 → 顶部出现，计数 `Comments (N)` 递增
4. 对该评论 👍 → 数字 +1 且高亮；再点 👍 → 取消；点 👎 → 切换（赞减踩增）
5. 对该评论点 Reply → 内联输入框提交 → 出现「View 1 reply」，展开可见回复按时间正序
6. 对回复再点其内部的回复按钮 → **不存在**（回复项不显示 Reply/View replies，1 级 UI 生效）
7. 作者自己的评论有 Delete 按钮，他人的没有；普通用户点他人删除按钮不可见；moderator/admin 账号可见并可删任意
8. 删除后该评论变占位「This comment was deleted.」（斜体灰），其回复仍在
9. 排序切 Top/Newest 列表重排；长列表底部 Load more 分页
10. **不破坏既有**：视频仍能正常播放、切换画质

- [ ] **Step 3: 更新 README.md**

在「功能特性」列表末尾追加：

```markdown
- **评论与 1 级回复**：视频下评论、回复归入同一顶级线程；读公开、登录可写
- **评论赞/踩**：每人每评论一票，可切换/取消，反范式净分用于热度排序
- **评论治理**：作者软删除自己评论（留占位），moderator/admin 可删任意
```

在「API」的「用户管理」表之后追加：

```markdown
### 评论与点赞

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/videos/{video_id}/comments` | 公开 | 顶级评论分页，`?sort=top\|new&limit&offset`；登录附 `my_vote` |
| GET | `/api/comments/{id}/replies` | 公开 | 该线程回复，时间正序分页 |
| POST | `/api/videos/{video_id}/comments` | 登录 | body `{content, reply_to?}` 建评论/回复 |
| DELETE | `/api/comments/{id}` | 作者或 moderator+ | 软删除，204 |
| PUT | `/api/comments/{id}/vote` | 登录 | body `{value: 1\|-1\|0}`，0 撤票 |

投票计数走 `comments` 冗余列（`like_count/dislike_count/score`）+ `comment_votes(user_id, comment_id, value)` 主键唯一，`apply_vote` 单事务更新。模块位于 `app/comments/`（`schemas/service/router`），复用 `app/auth/dependencies` 的鉴权与 `ROLE_LEVEL`。
```

在「设计要点」列表末尾追加：

```markdown
- **评论读公开、写需登录**：列表/回复用 `get_optional_user`，登录才注入 `my_vote`；发表/投票用 `get_current_user`
- **1 级线程靠 root_id 归位**：回复的回复不新增层级，`root_id` 恒指向顶级评论，`parent_id` 记录“回复谁”
- **软删除保线程**：删除仅置 `status=deleted` 并屏蔽正文，回复链不断裂
- **反范式计数**：单写者事务内同步 `comment_votes` 与 `comments` 计数，排序走索引列，热读高效
```

- [ ] **Step 4: 确认无临时文件残留**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; $f=@(Get-ChildItem -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '_verify_comments*' -or $_.Name -like '_e2e_comments*' }); Write-Output "count=$($f.Count)"
```

Expected: `count=0`

- [ ] **Step 5: 提交 README**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes; git add youtube-system/README.md; git commit -m 'docs: document youtube comments and likes feature in README' *> $null; Write-Output exit=$LASTEXITCODE
```

Expected: `exit=0`

---

## 完成标准

- [ ] 规格 §1–§7 全部实现；§9「明确不做」项**未被实现**
- [ ] Task 1–4 的纯逻辑/路由验证脚本全部通过（`COMMENTS_DB_OK`/`COMMENTS_READ_OK`/`COMMENTS_VOTE_OK`/`COMMENT_ROUTES_OK`）
- [ ] Task 5 后端 e2e `COMMENTS_E2E_OK`
- [ ] Task 7/8 前端 `build_exit=0`、容器部署 `deploy_exit=0`、手测清单 §Step 2 全通过
- [ ] 既有「上传→转码→播放」链路与用户系统未被破坏（Task 8 Step 2 第 10 项）
- [ ] 所有临时验证/e2e 脚本已删除（Task 8 Step 4 `count=0`）
- [ ] `1 级回复`「扁平归位同一 root_id」、投票四态计数、软删权限矩阵均有测试覆盖

---

## Self-Review（写完后自查）

- **Spec coverage**：§1 功能面 → Task 2/3/7；§2 数据模型 → Task 1；§3 模块结构 → Task 2/3/4；§4 API+鉴权+投影 → Task 4（端点）+ Task 2/3（`_out`/`my_vote`）；§5 建/投票/列表 → Task 2/3；§6 前端 → Task 6/7；§7 错误边界 → 各 service 抛领域异常、router 映射（含 422 由 Pydantic 保证）；§8 测试 → Task 1–5/7–8；§9 不做 → 无对应 Task。全部有落点。
- **Placeholder**：无 TBD/TODO；每个改动步给出完整代码与确切命令+期望输出。
- **类型一致性**：`database.apply_vote/get_comment/insert_comment/list_top_comments/list_replies/count_replies/reply_counts/viewer_votes/soft_delete_comment` 签名在 Task 1 定义、Task 2/3 调用一致；`service._out/vote/delete_comment/create_comment/list_comments/list_replies` 命名前后一致；`CommentOut` 字段与 `_out` 返回键一致；前端函数名 `listComments/listReplies/createComment/deleteComment/voteComment` 在 Task 6 定义、Task 7 调用一致；`my_vote/like_count/dislike_count/score/reply_count/root_id/parent_id` 跨层同名。
