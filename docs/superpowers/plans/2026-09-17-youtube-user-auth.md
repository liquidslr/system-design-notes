# MyTube 用户系统与登录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为已运行的 `youtube-system`（视频上传→转码→HLS 播放）新增用户注册/登录、四级角色权限、视频归属与管理后台。

**Architecture:** 模块化单体——在现有 `api-server` 容器内新增 `app/auth/` 子包（schemas / security / service / dependencies / router），users 表并入同一 SQLite（api-server 仍是唯一写者），refresh token 存 Redis。不新增容器。前端新增 `tokens.js`/`auth.js` 两个模块与 4 个视图，axios 拦截器实现 401 单飞刷新重放。

**Tech Stack:** FastAPI 0.115 · PyJWT 2.9 · bcrypt 4.2 · aiosqlite · redis-py 5 · Vue 3 · vue-router 4 · axios · Vite 5

**规格：** `docs/superpowers/specs/2026-09-17-youtube-user-auth-design.md`（下文简称「规格」，章节号引用均指该文档）

---

## 执行前必读：环境约束

本项目开发机为 **Windows 11 + PowerShell**，以下限制在上一轮实施中已多次踩坑，务必遵守：

| 约束 | 做法 |
|------|------|
| PowerShell **不支持 `&&`** | 命令分隔一律用 `;` |
| `curl` 是 `Invoke-WebRequest` 别名 | 需要真 curl 时用 `curl.exe`；本项目验证统一用 Python `requests` 脚本 |
| PowerShell 内联 JSON 转义极易出错 | 任何带 JSON body 的验证都写成 `.py` 脚本文件执行 |
| Python 解释器 | 宿主用 `D:\StudyProjects\system-design-notes\venv\Scripts\python.exe` |
| pip 装包 | 加 `-i https://pypi.tuna.tsinghua.edu.cn/simple --retries 10 --timeout 120` |
| npm 装包 | 加 `--registry=https://registry.npmmirror.com` |
| 长耗时命令 | `is_background=true` 后用 `GetTerminalOutput` 轮询；**不要**用 `Select-Object -Last N` 管道（会吞掉全部流式输出直到进程结束） |
| 项目根 | 所有 `docker compose` 命令前先 `Set-Location D:\StudyProjects\system-design-notes\youtube-system` |

**本项目无单元测试框架**（无 pytest、无 tests/ 目录）。上一轮的验证方式是「临时 e2e 脚本 + 人工前端清单，验证通过后删除脚本」，规格 §8 已沿用该方式。因此本计划的每个任务都以**可执行的验证步骤**收尾（`py_compile`、临时校验脚本、e2e 脚本、人工清单），而不是引入 pytest。请勿自行添加测试框架——那会偏离已批准的规格 §8。

**两处对规格字面表述的实现细化**（不改变规格语义，实施时按下述执行）：

1. **种子账号创建位置**：规格 §1.4 写「`init_db()` 中幂等创建」。但 §3 规定依赖方向为 `service → (security, database)`，若 `database.py` 反向 import `auth.security` 做 bcrypt 哈希即违反该规则。故实现为：`app/auth/service.py` 提供 `ensure_seed_users()`，由 `app/server.py` 的 lifespan 在 `init_db()` 之后调用。种子逻辑仍在启动时幂等执行，只是物理位置在 service 层。
2. **前端新增 `tokens.js`**：规格 §5.1 要求 `api.js` 含拦截器、`auth.js` 含令牌存储，而拦截器需要读写令牌 → 两模块互相 import 形成循环。故抽出零依赖的 `tokens.js` 承载 localStorage 读写，`api.js` 与 `auth.js` 各自单向依赖它，`auth.js` 再 re-export 以满足规格 §5.1 列出的导出清单。

---

## File Structure

**后端（`youtube-system/`）**

| 文件 | 动作 | 职责 |
|------|------|------|
| `requirements.txt` | 改 | 增加 PyJWT、bcrypt |
| `app/config.py` | 改 | 增加 `jwt_secret` / `access_token_ttl` / `refresh_token_ttl` |
| `app/database.py` | 改 | users 建表、`videos.uploader_id` 幂等迁移、用户 CRUD、视频查询 LEFT JOIN |
| `app/presign.py` | 改 | `issue()` 记录归属、`consume()` 转移归属、新增 `claim_owner()` |
| `app/server.py` | 改 | 挂载 auth 路由、种子账号、bind_redis、现有端点加鉴权、`/api/videos/mine` |
| `app/auth/__init__.py` | 新 | 包声明 |
| `app/auth/schemas.py` | 新 | 请求/响应 Pydantic 模型 |
| `app/auth/security.py` | 新 | 纯函数：bcrypt、JWT 编解码、ROLE_LEVEL、refresh 键构造 |
| `app/auth/service.py` | 新 | 业务逻辑：注册/登录/刷新/登出/用户管理；唯一触碰 users 表与 refresh 键 |
| `app/auth/dependencies.py` | 新 | `CurrentUser`、`get_current_user`、`get_optional_user`、`require_role` |
| `app/auth/router.py` | 新 | `/api/auth/*` 与 `/api/users/*` 端点，领域异常 → HTTP 码 |
| `docker-compose.yml` | 改 | api-server 增加 3 个环境变量 |

**前端（`youtube-system/frontend/src/`）**

| 文件 | 动作 | 职责 |
|------|------|------|
| `tokens.js` | 新 | localStorage 令牌读写（零依赖，打破循环） |
| `api.js` | 改 | axios 实例 + 双向拦截器 + 全部端点函数 + `extractError` |
| `auth.js` | 新 | `authState`、`restore/login/register/logout/hasRole`、`ROLE_LEVEL` |
| `router.js` | 改 | 新增 4 路由 + `beforeEach` 守卫 |
| `main.js` | 改 | 注册 auth 失败处理器；`restore()` 后再 mount |
| `App.vue` | 改 | 导航栏身份态 + 用户下拉菜单 |
| `style.css` | 改 | 追加 auth/dropdown/table/hint 样式 |
| `views/LoginView.vue` | 新 | 登录表单 + redirect 回跳 |
| `views/RegisterView.vue` | 新 | 注册表单（成功后自动登录） |
| `views/MyVideosView.vue` | 新 | 我的上传（含 failed，可重试） |
| `views/AdminUsersView.vue` | 新 | 用户表格 + 改角色 + 封禁/解封 + 分页 |
| `views/HomeView.vue` | 改 | 卡片显示上传者 |
| `views/UploadView.vue` | 改 | 角色不足提示 |
| `views/WatchView.vue` | 改 | 显示上传者；retry 按钮权限化 |

**文档**：`youtube-system/README.md`（改）

---

## Task 1: 依赖与配置

**Files:**
- Modify: `youtube-system/requirements.txt`
- Modify: `youtube-system/app/config.py`

- [ ] **Step 1: 增加两个依赖**

`requirements.txt` 改为完整内容：

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
aiosqlite==0.20.0
pydantic==2.9.2
redis==5.0.8
PyJWT==2.9.0
bcrypt==4.2.0
```

不引入 `passlib`（已停止维护，对 bcrypt 4.x 有兼容告警）；不引入 `email-validator`（邮箱格式用正则即可，见 Task 4）。

- [ ] **Step 2: config.py 增加认证字段**

在 `app/config.py` 的 `allowed_exts` 行之后、`config = Config()` 之前插入：

```python
    # Auth: JWT access token (stateless) + opaque refresh token (Redis)
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-in-production")
    access_token_ttl: int = int(os.getenv("ACCESS_TOKEN_TTL", "900"))       # 15min
    refresh_token_ttl: int = int(os.getenv("REFRESH_TOKEN_TTL", "604800"))  # 7d
    ban_marker_ttl: int = int(os.getenv("BAN_MARKER_TTL", "86400"))         # 1d, see spec 2.5
```

改完后 `Config` 的完整字段顺序应为：`db_path, original_dir, transcoded_dir, host, port, redis_url, task_queue, event_queue, presign_ttl, max_upload_bytes, allowed_exts, jwt_secret, access_token_ttl, refresh_token_ttl, ban_marker_ttl`。

- [ ] **Step 3: 本地安装新依赖（供后续任务的临时校验脚本使用）**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes; .\venv\Scripts\pip.exe install PyJWT==2.9.0 bcrypt==4.2.0 -i https://pypi.tuna.tsinghua.edu.cn/simple --retries 10 --timeout 120
```

Expected: `Successfully installed PyJWT-2.9.0 bcrypt-4.2.0`（若已存在则显示 `Requirement already satisfied`）

- [ ] **Step 4: 验证配置可加载且环境变量生效**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -c "from app.config import config; print(config.jwt_secret, config.access_token_ttl, config.refresh_token_ttl)"
```

Expected: `dev-only-secret-change-in-production 900 604800`

再验证环境变量覆盖：

```powershell
$env:ACCESS_TOKEN_TTL="30"; ..\venv\Scripts\python.exe -c "from app.config import config; print(config.access_token_ttl)"; Remove-Item Env:\ACCESS_TOKEN_TTL
```

Expected: `30`

---

## Task 2: 数据层——users 表、uploader_id 迁移、查询函数

**Files:**
- Modify: `youtube-system/app/database.py`

现有 `database.py` 共 152 行，`init_db()` 用一次 `executescript` 建 `videos` + `renditions`。本任务在其后追加 users 表与迁移逻辑，并新增用户相关函数、改造视频查询。

- [ ] **Step 1: 改造 `init_db()`**

将现有 `init_db()` 整体替换为（`videos`/`renditions` 建表语句保持原样不动，仅在其后追加）：

```python
async def init_db() -> None:
    os.makedirs(os.path.dirname(config.db_path), exist_ok=True)
    async with aiosqlite.connect(config.db_path) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                original_path TEXT,
                duration_sec REAL,
                width INTEGER,
                height INTEGER,
                error_msg TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS renditions (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL REFERENCES videos(id),
                resolution TEXT NOT NULL,
                playlist_path TEXT,
                bitrate_kbps INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(video_id, resolution)
            );
            CREATE INDEX IF NOT EXISTS idx_renditions_video ON renditions(video_id);
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        # videos.uploader_id is nullable: rows created before the user system
        # stay anonymous. SQLite has no ADD COLUMN IF NOT EXISTS, so probe first.
        cursor = await db.execute("PRAGMA table_info(videos)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "uploader_id" not in columns:
            await db.execute(
                "ALTER TABLE videos ADD COLUMN uploader_id TEXT REFERENCES users(id)")
            logger.info("Migrated videos: added uploader_id column")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_uploader ON videos(uploader_id)")
        await db.commit()
    logger.info("Database initialized")
```

- [ ] **Step 2: `insert_video()` 增加 uploader_id 参数**

替换为：

```python
async def insert_video(video_id: str, title: str, description: str,
                       original_path: str, uploader_id: str | None = None) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO videos (id, title, description, status, original_path,
                                   uploader_id, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 original_path=excluded.original_path,
                 uploader_id=excluded.uploader_id, status='pending',
                 error_msg=NULL, updated_at=excluded.updated_at""",
            (video_id, title, description, original_path, uploader_id, now, now),
        )
        await db.commit()
```

默认值 `None` 保持对现有调用方的兼容（Task 6 才传入真实 user id）。

- [ ] **Step 3: `get_video()` / `list_videos()` 改为 LEFT JOIN，新增 `list_videos_by_uploader()`**

替换 `get_video` 与 `list_videos`，并在其后新增一个函数：

```python
_VIDEO_SELECT = """
    SELECT v.*, u.username AS uploader_username
    FROM videos v LEFT JOIN users u ON v.uploader_id = u.id
"""


async def get_video(video_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT + " WHERE v.id = ?", (video_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_videos() -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(_VIDEO_SELECT + " ORDER BY v.created_at DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def list_videos_by_uploader(uploader_id: str) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT + " WHERE v.uploader_id = ? ORDER BY v.created_at DESC",
            (uploader_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]
```

`_VIDEO_SELECT` 常量放在 `init_db()` 之后、`insert_video()` 之前。JOIN 后每行必含 `uploader_id` 与 `uploader_username` 两键（匿名视频值为 `None`），Task 6 的 `_card()` 依赖这一点。

- [ ] **Step 4: 新增用户相关函数**

追加到 `database.py` 末尾（`count_by_status()` 之后）：

```python
async def insert_user(user_id: str, username: str, email: str,
                      password_hash: str, role: str) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO users (id, username, email, password_hash, role,
                                  status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
            (user_id, username, email, password_hash, role, now, now),
        )
        await db.commit()


async def get_user_by_email(email: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_username(username: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_users(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_users() -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0]


async def set_user_role(user_id: str, role: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
            (role, time.time(), user_id),
        )
        await db.commit()


async def set_user_status(user_id: str, status: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), user_id),
        )
        await db.commit()
```

- [ ] **Step 5: 语法检查**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/database.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

- [ ] **Step 6: 验证迁移幂等性与 JOIN 行为**

创建临时校验脚本 `youtube-system/_verify_db.py`：

```python
"""Temporary check: init_db idempotency, uploader_id migration, JOIN shape."""
import asyncio
import os
import sqlite3
import time

os.environ["DB_PATH"] = "data/_verify.db"
if os.path.exists("data/_verify.db"):
    os.remove("data/_verify.db")

# Pre-create a legacy videos table WITHOUT uploader_id to simulate the
# database left over from the previous round.
os.makedirs("data", exist_ok=True)
legacy = sqlite3.connect("data/_verify.db")
legacy.execute("""CREATE TABLE videos (
    id TEXT PRIMARY KEY, title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
    original_path TEXT, duration_sec REAL, width INTEGER, height INTEGER,
    error_msg TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
t = time.time()
legacy.execute("INSERT INTO videos (id,title,created_at,updated_at) VALUES (?,?,?,?)",
               ("legacy0001", "Legacy anonymous", t, t))
legacy.commit()
legacy.close()

from app import database  # noqa: E402  (imports after DB_PATH is set)
from app.config import config  # noqa: E402


async def main():
    assert config.db_path == "data/_verify.db", config.db_path

    await database.init_db()
    await database.init_db()  # second run must not raise (idempotent migration)

    legacy_row = await database.get_video("legacy0001")
    assert legacy_row is not None, "legacy row lost"
    assert legacy_row["uploader_id"] is None, legacy_row["uploader_id"]
    assert legacy_row["uploader_username"] is None, "JOIN must yield NULL username"

    await database.insert_user("u1", "alice", "alice@t.local", "hash", "user")
    await database.insert_video("v2", "Owned", "", "/tmp/x.mp4", uploader_id="u1")
    owned = await database.get_video("v2")
    assert owned["uploader_id"] == "u1", owned
    assert owned["uploader_username"] == "alice", owned

    mine = await database.list_videos_by_uploader("u1")
    assert [r["id"] for r in mine] == ["v2"], mine
    allv = await database.list_videos()
    assert {r["id"] for r in allv} == {"legacy0001", "v2"}, allv

    assert await database.count_users() == 1
    assert (await database.get_user_by_email("alice@t.local"))["username"] == "alice"
    assert (await database.get_user_by_username("alice"))["id"] == "u1"
    assert (await database.get_user_by_id("u1"))["role"] == "user"
    assert await database.get_user_by_id("nope") is None

    await database.set_user_role("u1", "creator")
    await database.set_user_status("u1", "banned")
    row = await database.get_user_by_id("u1")
    assert (row["role"], row["status"]) == ("creator", "banned"), row

    page = await database.list_users(limit=10, offset=0)
    assert len(page) == 1 and page[0]["username"] == "alice", page

    print("DB_VERIFY_OK")


asyncio.run(main())
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_db.py
```

Expected: `DB_VERIFY_OK`

若报 `sqlite3.OperationalError: duplicate column name` → Step 1 的 `PRAGMA table_info` 检测未生效；若报 `no such column: uploader_id` → ALTER 未执行。

- [ ] **Step 7: 清理临时文件**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item _verify_db.py, data\_verify.db -Force -ErrorAction SilentlyContinue; Write-Output "cleaned"
```

Expected: `cleaned`

---

## Task 3: `app/auth/security.py`——纯函数加密层

**Files:**
- Create: `youtube-system/app/auth/__init__.py`
- Create: `youtube-system/app/auth/security.py`

本模块**不做任何 IO**（不碰 SQLite、不碰 Redis），因此可在无容器的情况下直接验证。

- [ ] **Step 1: 创建包声明文件**

`app/auth/__init__.py`（注意：空文件会被写入工具拒绝，必须带 docstring）：

```python
"""Authentication and user-management subpackage (spec section 3)."""
```

- [ ] **Step 2: 写 security.py**

```python
"""Pure crypto/token helpers: bcrypt hashing, JWT codec, role levels.

No IO in this module - it never touches SQLite or Redis. That keeps it
directly verifiable and preserves the one-way dependency rule
(router -> service -> security, dependencies -> security).
"""
import hashlib
import secrets
import time

import bcrypt
import jwt

from app.config import config

# Role hierarchy (spec 1.3). Higher level implicitly includes lower ones;
# the frontend keeps an identically-named copy in src/auth.js.
ROLES = ("user", "creator", "moderator", "admin")
ROLE_LEVEL = {"user": 1, "creator": 2, "moderator": 3, "admin": 4}

_ALGO = "HS256"


class InvalidTokenError(Exception):
    """Access token cannot be trusted: bad signature, expired, or wrong shape."""


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False  # malformed hash in DB - treat as wrong password


def create_access_token(user_id: str, username: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + config.access_token_ttl,
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=_ALGO)


def decode_access_token(token: str) -> dict:
    """Verify signature + expiry locally. Never queries the DB or Redis -
    that is the whole point of the stateless access token (spec 2.1)."""
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=[_ALGO])
    except jwt.PyJWTError as e:
        raise InvalidTokenError(str(e)) from e
    if payload.get("type") != "access" or not payload.get("sub"):
        raise InvalidTokenError("not an access token")
    return payload


def make_refresh_token(user_id: str) -> str:
    """Opaque random string prefixed with the owner id.

    The prefix is what makes replay protection possible (spec 2.2/2.3): when a
    submitted token is absent from Redis we must still know whose sessions to
    revoke, and the client only sends the token itself.
    """
    return f"{user_id}.{secrets.token_urlsafe(48)}"


def split_refresh_token(token: str) -> str | None:
    """Return the owning user_id, or None if the token is malformed."""
    user_id, sep, _ = token.partition(".")
    return user_id if sep and user_id else None


def hash_token(token: str) -> str:
    """Only the SHA-256 of a refresh token is ever stored (spec 2.2)."""
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_key(user_id: str, token: str) -> str:
    return f"refresh:{user_id}:{hash_token(token)}"


def refresh_prefix(user_id: str) -> str:
    return f"refresh:{user_id}:"


def ban_key(user_id: str) -> str:
    """Redis key marking a user as banned. get_current_user checks EXISTS on it
    (one O(1) GET, no DB) so a ban revokes even a live access token immediately
    (spec 2.5)."""
    return f"auth:ban:{user_id}"
```

- [ ] **Step 3: 语法检查**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/auth/__init__.py app/auth/security.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

- [ ] **Step 4: 行为验证**

创建临时脚本 `youtube-system/_verify_security.py`：

```python
"""Temporary check: bcrypt round-trip, JWT codec, refresh key derivation."""
import time

import jwt as pyjwt

from app.auth import security
from app.config import config

# --- bcrypt ---
h = security.hash_password("Passw0rd!")
assert h != "Passw0rd!" and h.startswith("$2"), h
assert security.verify_password("Passw0rd!", h) is True
assert security.verify_password("wrong", h) is False
assert security.verify_password("Passw0rd!", "not-a-hash") is False
assert security.hash_password("Passw0rd!") != h, "salt must differ per call"

# --- roles ---
assert security.ROLES == ("user", "creator", "moderator", "admin")
assert security.ROLE_LEVEL["admin"] > security.ROLE_LEVEL["moderator"] \
    > security.ROLE_LEVEL["creator"] > security.ROLE_LEVEL["user"]

# --- JWT round-trip ---
tok = security.create_access_token("uid123", "alice", "creator")
p = security.decode_access_token(tok)
assert (p["sub"], p["username"], p["role"], p["type"]) == \
    ("uid123", "alice", "creator", "access"), p
assert p["exp"] - p["iat"] == config.access_token_ttl, p

# --- JWT rejects tampering, wrong secret, expiry, wrong type ---
for bad, why in [
    (tok[:-2] + "xx", "tampered signature"),
    (pyjwt.encode({"sub": "u", "type": "access", "exp": int(time.time()) + 60},
                  "another-secret", algorithm="HS256"), "wrong secret"),
    (pyjwt.encode({"sub": "u", "type": "access", "exp": int(time.time()) - 10},
                  config.jwt_secret, algorithm="HS256"), "expired"),
    (pyjwt.encode({"sub": "u", "type": "refresh", "exp": int(time.time()) + 60},
                  config.jwt_secret, algorithm="HS256"), "wrong type"),
    (pyjwt.encode({"type": "access", "exp": int(time.time()) + 60},
                  config.jwt_secret, algorithm="HS256"), "missing sub"),
]:
    try:
        security.decode_access_token(bad)
        raise AssertionError(f"should have rejected: {why}")
    except security.InvalidTokenError:
        pass

# --- refresh token shape + key derivation ---
rt = security.make_refresh_token("uid123")
assert security.split_refresh_token(rt) == "uid123", rt
assert security.split_refresh_token("no-separator") is None
assert security.split_refresh_token(".abc") is None
key = security.refresh_key("uid123", rt)
assert key.startswith("refresh:uid123:") and len(key.split(":")[-1]) == 64, key
assert security.refresh_prefix("uid123") == "refresh:uid123:"
assert security.hash_token(rt) != rt, "must never store the raw token"

print("SECURITY_VERIFY_OK")
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_security.py
```

Expected: `SECURITY_VERIFY_OK`

- [ ] **Step 5: 清理临时文件**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item _verify_security.py -Force -ErrorAction SilentlyContinue; Write-Output "cleaned"
```

Expected: `cleaned`

---

## Task 4: `schemas.py` + `service.py`——业务层

**Files:**
- Create: `youtube-system/app/auth/schemas.py`
- Create: `youtube-system/app/auth/service.py`

`service.py` 是**唯一**触碰 users 表与 refresh 键的模块（规格 §3）。它抛领域异常，不感知 HTTP。

- [ ] **Step 1: 写 schemas.py**

```python
"""Pydantic models for the auth + user-management API (spec 4.2/4.4)."""
from pydantic import BaseModel, Field, field_validator

# Kept as regexes rather than pulling in email-validator: this is a learning
# project and the spec only asks for "standard format" (spec 4.4).
USERNAME_RE = r"^[a-zA-Z0-9_]+$"
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# bcrypt rejects passwords longer than 72 bytes, so the cap is enforced here
# (422) instead of surfacing as a 500 from the hashing call.
PASSWORD_MAX = 72


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=USERNAME_RE)
    email: str = Field(..., min_length=3, max_length=254, pattern=EMAIL_RE)
    password: str = Field(..., min_length=8, max_length=PASSWORD_MAX)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    # Deliberately NOT min_length=8: a wrong short password must produce the
    # same 401 as a wrong long one, never a 422 (spec 4.4: no enumeration).
    password: str = Field(..., min_length=1, max_length=PASSWORD_MAX)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=20, max_length=256)


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=20)


class BanRequest(BaseModel):
    reason: str = Field("", max_length=500)


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: str
    status: str
    created_at: float


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
```

- [ ] **Step 2: 写 service.py**

```python
"""Auth + user-management business logic (spec 3).

The ONLY module that touches the users table and the refresh-token keys.
Raises domain exceptions; router.py maps them to HTTP status codes so this
layer stays HTTP-agnostic.
"""
import json
import logging
import secrets
import time

from app import database
from app.auth import security
from app.config import config

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """401 - bad credentials, or a refresh token we cannot honour."""


class PermissionError(Exception):  # noqa: A001 - name mandated by spec 3
    """403 - identified, but not allowed (banned account)."""


class ConflictError(Exception):
    """409 - username or email already taken."""


class NotFoundError(Exception):
    """404 - user does not exist."""


class ValidationError(Exception):
    """400 - invalid input Pydantic cannot express (bad role, self-target)."""


# Redis handle, injected once from the api-server lifespan. Injection (rather
# than `from app.server import redis`) keeps the dependency one-way.
_redis = None


def bind_redis(client) -> None:
    global _redis
    _redis = client


# Local-testing accounts only (spec 1.4). README must flag these as insecure.
SEED_USERS = (
    {"username": "admin", "email": "admin@mytube.local",
     "password": "Admin@123", "role": "admin"},
    {"username": "creator", "email": "creator@mytube.local",
     "password": "Creator@123", "role": "creator"},
)


async def ensure_seed_users() -> None:
    """Idempotent: skips any seed username that already exists."""
    for seed in SEED_USERS:
        if await database.get_user_by_username(seed["username"]) is not None:
            continue
        await database.insert_user(
            secrets.token_hex(12), seed["username"], seed["email"],
            security.hash_password(seed["password"]), seed["role"],
        )
        logger.info("Seeded %s account %r", seed["role"], seed["username"])


def _user_out(row: dict) -> dict:
    return {
        "id": row["id"], "username": row["username"], "email": row["email"],
        "role": row["role"], "status": row["status"],
        "created_at": row["created_at"],
    }


async def revoke_all_refresh(user_id: str) -> int:
    """Drop every session of a user (logout, ban, replay defence)."""
    prefix = security.refresh_prefix(user_id)
    deleted = 0
    async for key in _redis.scan_iter(match=f"{prefix}*", count=100):
        await _redis.delete(key)
        deleted += 1
    return deleted


async def _issue_tokens(user: dict) -> dict:
    access = security.create_access_token(
        user["id"], user["username"], user["role"])
    refresh = security.make_refresh_token(user["id"])
    await _redis.set(
        security.refresh_key(user["id"], refresh),
        json.dumps({"issued_at": int(time.time())}),
        ex=config.refresh_token_ttl,
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": config.access_token_ttl,
        "user": _user_out(user),
    }


async def register(username: str, email: str, password: str) -> dict:
    """Create a 'user'-role account. Returns no tokens (spec 4.2)."""
    if await database.get_user_by_email(email):
        raise ConflictError("email is already registered")
    if await database.get_user_by_username(username):
        raise ConflictError("username is already taken")
    user_id = secrets.token_hex(12)
    await database.insert_user(
        user_id, username, email, security.hash_password(password), "user")
    row = await database.get_user_by_id(user_id)
    logger.info("Registered user %s (%s)", username, user_id)
    return _user_out(row)


async def login(email: str, password: str) -> dict:
    user = await database.get_user_by_email(email)
    # One message for both failure modes - no account enumeration (spec 4.4).
    if user is None or not security.verify_password(password, user["password_hash"]):
        raise AuthError("invalid email or password")
    if user["status"] != "active":
        raise PermissionError("account is banned")
    return await _issue_tokens(user)


async def refresh(refresh_token: str) -> dict:
    """Rotate the refresh token; treat a replayed one as a breach (spec 2.3)."""
    user_id = security.split_refresh_token(refresh_token)
    if user_id is None:
        raise AuthError("invalid refresh token")

    key = security.refresh_key(user_id, refresh_token)
    if await _redis.get(key) is None:
        # Absent == already rotated away == probable replay: kill every session
        # this user has and force a re-login.
        revoked = await revoke_all_refresh(user_id)
        logger.warning("Refresh replay suspected for user %s; revoked %d tokens",
                       user_id, revoked)
        raise AuthError("invalid refresh token")

    user = await database.get_user_by_id(user_id)
    if user is None:
        await _redis.delete(key)
        raise AuthError("invalid refresh token")
    if user["status"] != "active":
        # Ban takes effect here at the latest (spec 2.5, layer 3).
        await revoke_all_refresh(user_id)
        raise AuthError("account is banned")

    await _redis.delete(key)
    return await _issue_tokens(user)


async def logout(user_id: str) -> None:
    await revoke_all_refresh(user_id)


async def get_me(user_id: str) -> dict:
    row = await database.get_user_by_id(user_id)
    if row is None:
        raise NotFoundError("user not found")
    return _user_out(row)


async def get_public_user(user_id: str) -> dict:
    """Public projection - never leaks email or status (spec 4.2)."""
    row = await database.get_user_by_id(user_id)
    if row is None:
        raise NotFoundError("user not found")
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


async def list_users(limit: int, offset: int) -> dict:
    rows = await database.list_users(limit, offset)
    return {"users": [_user_out(r) for r in rows],
            "total": await database.count_users()}


async def set_role(actor_id: str, target_id: str, role: str) -> dict:
    if role not in security.ROLES:
        raise ValidationError(f"role must be one of: {', '.join(security.ROLES)}")
    if actor_id == target_id:
        raise ValidationError("cannot change your own role")
    if await database.get_user_by_id(target_id) is None:
        raise NotFoundError("user not found")
    await database.set_user_role(target_id, role)
    logger.info("Role of user %s set to %s by %s", target_id, role, actor_id)
    return _user_out(await database.get_user_by_id(target_id))


async def ban(actor_id: str, target_id: str, reason: str = "") -> dict:
    if actor_id == target_id:
        raise ValidationError("cannot ban yourself")
    if await database.get_user_by_id(target_id) is None:
        raise NotFoundError("user not found")
    await database.set_user_status(target_id, "banned")
    revoked = await revoke_all_refresh(target_id)
    # Immediate-revocation marker: get_current_user rejects any live access
    # token once this key exists (spec 2.5).
    await _redis.set(security.ban_key(target_id), "1", ex=config.ban_marker_ttl)
    logger.info("Banned user %s (reason=%r); revoked %d refresh tokens",
                target_id, reason, revoked)
    return _user_out(await database.get_user_by_id(target_id))


async def unban(target_id: str) -> dict:
    if await database.get_user_by_id(target_id) is None:
        raise NotFoundError("user not found")
    await database.set_user_status(target_id, "active")
    await _redis.delete(security.ban_key(target_id))
    logger.info("Unbanned user %s", target_id)
    return _user_out(await database.get_user_by_id(target_id))
```

- [ ] **Step 3: 语法检查**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/auth/schemas.py app/auth/service.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

- [ ] **Step 4: 验证 Pydantic 校验规则**

创建临时脚本 `youtube-system/_verify_schemas.py`：

```python
"""Temporary check: request validation rules from spec 4.4."""
from pydantic import ValidationError as PydanticError

from app.auth.schemas import (BanRequest, LoginRequest, RefreshRequest,
                              RegisterRequest, RoleUpdateRequest)


def ok(model, **kw):
    return model(**kw)


def bad(model, **kw):
    try:
        model(**kw)
    except PydanticError:
        return True
    raise AssertionError(f"{model.__name__} should have rejected {kw}")


GOOD = {"username": "alice_01", "email": "Alice@Example.com", "password": "Passw0rd!"}

r = ok(RegisterRequest, **GOOD)
assert r.email == "alice@example.com", r.email      # lowercased + trimmed
assert r.username == "alice_01"

bad(RegisterRequest, username="ab", email="a@b.com", password="Passw0rd!")   # <3
bad(RegisterRequest, username="x" * 33, email="a@b.com", password="Passw0rd!")
bad(RegisterRequest, username="has space", email="a@b.com", password="Passw0rd!")
bad(RegisterRequest, username="dash-name", email="a@b.com", password="Passw0rd!")
bad(RegisterRequest, username="ok_name", email="not-an-email", password="Passw0rd!")
bad(RegisterRequest, username="ok_name", email="a@b", password="Passw0rd!")
bad(RegisterRequest, username="ok_name", email="a@b.com", password="short1")  # <8
bad(RegisterRequest, username="ok_name", email="a@b.com", password="x" * 73)  # >72

# Login must NOT 422 on a short password - it has to reach the 401 path.
lg = ok(LoginRequest, email="  Alice@Example.com ", password="x")
assert lg.email == "alice@example.com" and lg.password == "x", lg
bad(LoginRequest, email="a@b.com", password="")   # empty still rejected

bad(RefreshRequest, refresh_token="short")
ok(RefreshRequest, refresh_token="uid." + "a" * 40)

bad(RoleUpdateRequest, role="")
ok(RoleUpdateRequest, role="superuser")   # length-valid; service layer rejects the value

assert BanRequest().reason == ""
assert BanRequest(reason="spam").reason == "spam"

print("SCHEMAS_VERIFY_OK")
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_schemas.py
```

Expected: `SCHEMAS_VERIFY_OK`

- [ ] **Step 5: 用假 Redis 验证 service 的令牌轮换与重放防护**

创建临时脚本 `youtube-system/_verify_service.py`（使用独立的临时 DB 与内存假 Redis，不触碰真实数据）：

```python
"""Temporary check: register/login/refresh rotation, replay defence, ban, roles."""
import asyncio
import fnmatch
import os

os.environ["DB_PATH"] = "data/_verify_svc.db"
os.makedirs("data", exist_ok=True)
if os.path.exists("data/_verify_svc.db"):
    os.remove("data/_verify_svc.db")

from app import database  # noqa: E402
from app.auth import security, service  # noqa: E402


class FakeRedis:
    """Minimal in-memory stand-in for redis.asyncio (set/get/delete/scan_iter)."""

    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)

    async def scan_iter(self, match=None, count=None):
        for k in [k for k in self.store if fnmatch.fnmatch(k, match or "*")]:
            yield k


async def expect(exc, coro, why):
    """Await `coro` and assert it raises `exc`.

    This helper must itself be a coroutine: main() already runs inside
    asyncio.run(), and nesting another asyncio.run() would raise
    "cannot be called from a running event loop".
    """
    try:
        await coro
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}: {why}")


async def main():
    fake = FakeRedis()
    service.bind_redis(fake)
    await database.init_db()
    await service.ensure_seed_users()
    await service.ensure_seed_users()   # idempotent
    assert await database.count_users() == 2, "seeds must not duplicate"

    admin = await database.get_user_by_username("admin")
    assert admin["role"] == "admin" and admin["status"] == "active"

    # --- register ---
    # register receives an already-normalized email: the router validates via
    # RegisterRequest (which lowercases) before delegating here (see schemas).
    u = await service.register("alice", "alice@t.local", "Passw0rd!")
    assert u["role"] == "user" and u["email"] == "alice@t.local", u
    assert "password_hash" not in u and "password" not in u, u
    await expect(service.ConflictError,
                 service.register("alice", "x@t.local", "Passw0rd!"),
                 "duplicate username")
    await expect(service.ConflictError,
                 service.register("bob", "alice@t.local", "Passw0rd!"),
                 "duplicate email")

    # --- login ---
    pair = await service.login("alice@t.local", "Passw0rd!")
    assert pair["token_type"] == "bearer" and pair["expires_in"] == 900, pair
    assert pair["user"]["username"] == "alice"
    assert len(fake.store) == 1, fake.store
    await expect(service.AuthError,
                 service.login("alice@t.local", "nope"), "wrong password")
    await expect(service.AuthError,
                 service.login("ghost@t.local", "Passw0rd!"), "unknown email")

    # --- refresh rotation: old token dies, new one works ---
    old_rt = pair["refresh_token"]
    pair2 = await service.refresh(old_rt)
    assert pair2["refresh_token"] != old_rt
    await expect(service.AuthError, service.refresh(old_rt), "replayed old token")
    # replay revoked the freshly issued one too (spec 8.1 item 8)
    assert fake.store == {}, f"replay must revoke all sessions: {fake.store}"
    await expect(service.AuthError, service.refresh(pair2["refresh_token"]),
                 "new token revoked after replay")

    # malformed token is rejected without touching Redis
    await expect(service.AuthError, service.refresh("no-separator-here-xxxx"),
                 "malformed refresh token")

    # --- logout ---
    pair3 = await service.login("alice@t.local", "Passw0rd!")
    assert len(fake.store) == 1
    await service.logout(pair3["user"]["id"])
    assert fake.store == {}
    await expect(service.AuthError, service.refresh(pair3["refresh_token"]),
                 "refresh after logout")

    # --- ban revokes refresh tokens AND sets an immediate-revocation marker ---
    dave = await service.register("dave", "dave@t.local", "Passw0rd!")
    dp = await service.login("dave@t.local", "Passw0rd!")
    banned = await service.ban(admin["id"], dave["id"], "spam")
    assert banned["status"] == "banned"
    assert not [k for k in fake.store if k.startswith("refresh:")], \
        "ban must revoke all refresh tokens"
    assert security.ban_key(dave["id"]) in fake.store, \
        "ban must set the auth:ban marker (get_current_user -> 403)"
    await expect(service.PermissionError,
                 service.login("dave@t.local", "Passw0rd!"), "banned login")
    me = await service.get_me(dave["id"])
    assert me["status"] == "banned"
    await expect(service.ValidationError,
                 service.ban(admin["id"], admin["id"]), "self ban")
    await service.unban(dave["id"])
    assert security.ban_key(dave["id"]) not in fake.store, \
        "unban must clear the auth:ban marker"
    assert (await service.get_me(dave["id"]))["status"] == "active"

    # --- roles ---
    alice_uid = u["id"]
    upd = await service.set_role(admin["id"], alice_uid, "creator")
    assert upd["role"] == "creator"
    await expect(service.ValidationError,
                 service.set_role(admin["id"], admin["id"], "user"),
                 "self role change")
    await expect(service.ValidationError,
                 service.set_role(admin["id"], alice_uid, "superuser"),
                 "illegal role value")
    await expect(service.NotFoundError,
                 service.set_role(admin["id"], "nosuch", "user"),
                 "missing target")

    # --- projections & listing ---
    pub = await service.get_public_user(u["id"])
    assert set(pub) == {"id", "username", "role"}, pub
    page = await service.list_users(50, 0)
    assert page["total"] == 4 and len(page["users"]) == 4, page
    assert "password_hash" not in page["users"][0]
    await expect(service.NotFoundError,
                 service.get_public_user("nosuch"), "missing user")

    print("SERVICE_VERIFY_OK")


asyncio.run(main())
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_service.py
```

Expected: `SERVICE_VERIFY_OK`

注意：`expect()` 是协程，调用处一律 `await expect(...)` 并直接传入协程对象（不要包 `lambda`，也不要嵌套 `asyncio.run`）。若看到 `RuntimeWarning: coroutine ... was never awaited`，说明某处漏了 `await`。

- [ ] **Step 6: 清理临时文件**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item _verify_schemas.py, _verify_service.py, data\_verify_svc.db -Force -ErrorAction SilentlyContinue; Write-Output "cleaned"
```

Expected: `cleaned`

---

## Task 5: `dependencies.py` + `router.py`——HTTP 层

**Files:**
- Create: `youtube-system/app/auth/dependencies.py`
- Create: `youtube-system/app/auth/router.py`

- [ ] **Step 1: 写 dependencies.py**

```python
"""FastAPI dependencies: Bearer token -> CurrentUser (spec 4.1).

Uses the native HTTPBearer scheme so Swagger UI renders an Authorize button.
"""
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import security
from app.auth.security import InvalidTokenError

_bearer = HTTPBearer(auto_error=False)

# Redis handle injected from the api-server lifespan (the SAME client passed to
# service.bind_redis). get_current_user uses it for a single O(1) EXISTS check
# of the ban marker (spec 2.5).
_redis = None


def bind_redis(client) -> None:
    global _redis
    _redis = client


@dataclass
class CurrentUser:
    """Fields come from the JWT payload - no DB lookup. A banned user is
    rejected by get_current_user via a Redis marker (immediate, spec 2.5);
    only *role changes* still wait for the access token to be refreshed."""

    id: str
    username: str
    role: str


def _parse(creds: HTTPAuthorizationCredentials | None) -> CurrentUser | None:
    if creds is None or creds.scheme.lower() != "bearer":
        return None
    try:
        payload = security.decode_access_token(creds.credentials)
    except InvalidTokenError:
        return None
    return CurrentUser(
        id=payload["sub"],
        username=payload.get("username", ""),
        role=payload.get("role", "user"),
    )


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    user = _parse(creds)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    # One O(1) Redis EXISTS (no DB) makes a ban revoke even a live access token
    # immediately (spec 2.5). Guard on _redis so the module imports cleanly in
    # route-table checks that never bind a client.
    if _redis is not None and await _redis.exists(security.ban_key(user.id)):
        raise HTTPException(status_code=403, detail="account is banned")
    return user


async def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser | None:
    """For public endpoints: parse if present, never fail."""
    return _parse(creds)


def require_role(min_role: str) -> Callable:
    """Dependency factory enforcing ROLE_LEVEL[user.role] >= ROLE_LEVEL[min_role].

    Unknown roles (e.g. a value written by hand into the DB) are denied.
    """
    need = security.ROLE_LEVEL[min_role]

    async def _require(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if security.ROLE_LEVEL.get(user.role, 0) < need:
            raise HTTPException(
                status_code=403, detail=f"requires {min_role} role or above")
        return user

    return _require
```

> **注意：`get_optional_user` 本轮没有任何端点使用，这是有意为之，不是遗漏。** 规格 §4.1 要求定义它，是为下一轮「评论点赞」预留的——届时 `GET /api/videos/{id}` 需要「带令牌就返回 `is_liked`，不带也照样 200」。实现者**不要**因为「无人引用」而删掉它，也不要为它临时造一个端点（那会偏离规格 §4.2 的端点清单）。Step 3 的 `_verify_routes.py` 只校验路由集合，不会因为这个函数未被使用而失败。

- [ ] **Step 2: 写 router.py**

```python
"""HTTP layer for /api/auth/* and /api/users/* (spec 4.2).

Domain exceptions from service.py become status codes here, so the business
layer never imports fastapi.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth import service
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.auth.schemas import (BanRequest, LoginRequest, RefreshRequest,
                              RegisterRequest, RoleUpdateRequest, TokenPair,
                              UserOut)

logger = logging.getLogger(__name__)

router = APIRouter()

_admin = require_role("admin")


@router.post("/api/auth/register", status_code=201)
async def register(req: RegisterRequest):
    """Returns the user only - no tokens (spec 4.2); the client logs in next."""
    try:
        return {"user": await service.register(
            req.username, req.email, req.password)}
    except service.ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/auth/login", response_model=TokenPair)
async def login(req: LoginRequest):
    try:
        return await service.login(req.email, req.password)
    except service.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except service.PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/api/auth/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest):
    try:
        return await service.refresh(req.refresh_token)
    except service.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/api/auth/logout", status_code=204)
async def logout(user: CurrentUser = Depends(get_current_user)):
    await service.logout(user.id)
    return Response(status_code=204)


@router.get("/api/auth/me", response_model=UserOut)
async def me(user: CurrentUser = Depends(get_current_user)):
    try:
        return await service.get_me(user.id)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/users")
async def list_users(_: CurrentUser = Depends(_admin),
                     limit: int = Query(50, ge=1, le=100),
                     offset: int = Query(0, ge=0)):
    return await service.list_users(limit, offset)


@router.get("/api/users/{user_id}")
async def get_user(user_id: str):
    """Public projection: {id, username, role}."""
    try:
        return await service.get_public_user(user_id)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/api/users/{user_id}/role", response_model=UserOut)
async def change_role(user_id: str, req: RoleUpdateRequest,
                      actor: CurrentUser = Depends(_admin)):
    try:
        return await service.set_role(actor.id, user_id, req.role)
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/users/{user_id}/ban", response_model=UserOut)
async def ban_user(user_id: str,
                   actor: CurrentUser = Depends(_admin),
                   req: BanRequest | None = None):
    try:
        return await service.ban(actor.id, user_id, req.reason if req else "")
    except service.ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/users/{user_id}/unban", response_model=UserOut)
async def unban_user(user_id: str, _: CurrentUser = Depends(_admin)):
    try:
        return await service.unban(user_id)
    except service.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

`/api/users` 必须声明在 `/api/users/{user_id}` **之前**（FastAPI 按注册顺序匹配，虽然本例两者路径不冲突，但保持顺序可避免后续加子路径时踩坑）。

- [ ] **Step 3: 语法检查 + 路由表验证**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/auth/dependencies.py app/auth/router.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

再验证路由已正确注册（临时脚本 `youtube-system/_verify_routes.py`）：

```python
"""Temporary check: auth router exposes exactly the endpoints from spec 4.2."""
from fastapi import FastAPI

from app.auth.router import router

app = FastAPI()
app.include_router(router)

got = {(r.path, m) for r in app.routes for m in getattr(r, "methods", set())
       if r.path.startswith("/api/")}
want = {
    ("/api/auth/register", "POST"),
    ("/api/auth/login", "POST"),
    ("/api/auth/refresh", "POST"),
    ("/api/auth/logout", "POST"),
    ("/api/auth/me", "GET"),
    ("/api/users", "GET"),
    ("/api/users/{user_id}", "GET"),
    ("/api/users/{user_id}/role", "PATCH"),
    ("/api/users/{user_id}/ban", "POST"),
    ("/api/users/{user_id}/unban", "POST"),
}
missing, extra = want - got, got - want
assert not missing, f"missing: {missing}"
assert not extra, f"unexpected: {extra}"

order = [r.path for r in app.routes if r.path.startswith("/api/users")]
assert order.index("/api/users") < order.index("/api/users/{user_id}"), order

print("ROUTES_VERIFY_OK")
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_routes.py; Remove-Item _verify_routes.py -Force -ErrorAction SilentlyContinue
```

Expected: `ROUTES_VERIFY_OK`

---

## Task 6: 接线——presign 归属校验 + server.py 鉴权改造

**Files:**
- Modify: `youtube-system/app/presign.py`
- Modify: `youtube-system/app/server.py`

- [ ] **Step 1: presign.py 记录并校验归属**

将 `app/presign.py` 中 `_tokens` 声明之后的全部内容（`issue` 与 `consume`）替换为：

```python
# token -> {video_id, user_id, expires_at}. In-memory: single instance by design.
_tokens: dict[str, dict] = {}

# video_id -> user_id. Outlives the token, because POST /api/videos carries only
# a video_id and still has to prove who the pre-signed URL was issued to.
_owners: dict[str, str] = {}


def issue(filename: str, size: int, user_id: str) -> dict:
    ext = ext_of(filename)
    if ext not in config.allowed_exts:
        raise PresignError(
            f"Unsupported file type .{ext}; allowed: {', '.join(config.allowed_exts)}"
        )
    if size <= 0 or size > config.max_upload_bytes:
        raise PresignError(f"Size must be in (0, {config.max_upload_bytes}] bytes")

    video_id = secrets.token_hex(12)
    token = secrets.token_urlsafe(24)
    _tokens[token] = {
        "video_id": video_id,
        "user_id": user_id,
        "expires_at": time.time() + config.presign_ttl,
    }
    return {
        "token": token,
        "video_id": video_id,
        "upload_path": f"/api/upload/{token}",
        "expires_in": config.presign_ttl,
    }


def consume(token: str) -> dict | None:
    """Single-use consume; returns token info or None if invalid/expired."""
    info = _tokens.pop(token, None)
    if info is None or info["expires_at"] < time.time():
        return None
    # Carry the ownership over: the token dies here, but the video it produced
    # still has to be claimed by the same user in POST /api/videos.
    _owners[info["video_id"]] = info["user_id"]
    return info


def claim_owner(video_id: str, user_id: str) -> bool:
    """One-shot ownership check; consumes the mapping so it cannot be reused."""
    if _owners.get(video_id) != user_id:
        return False
    _owners.pop(video_id, None)
    return True
```

`PresignError` 与 `ext_of` 保持不变。`issue()` 的第三个参数 `user_id` 是**必填位置参数**——唯一的调用方是 `server.py`，在 Step 3 同步修改。

- [ ] **Step 2: server.py 导入与 lifespan**

将 `app/server.py` 顶部的 import 块替换为：

```python
"""FastAPI application exposing the upload + video management API."""
import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from app import database
from app import presign
from app.auth import security
from app.auth import service as auth_service
from app.auth import dependencies as auth_deps
from app.auth.dependencies import CurrentUser, get_current_user, require_role
from app.auth.router import router as auth_router
from app.completion_consumer import run_consumer
from app.config import config
from app.models import UploadUrlRequest, UploadUrlResponse, VideoCreateRequest
from app.presign import PresignError, ext_of
from app.queue import create_client, push_task
```

将 lifespan 中 `await database.init_db()` 与 `redis = create_client()` 两行替换为：

```python
    await database.init_db()
    await auth_service.ensure_seed_users()
    redis = create_client()
    auth_service.bind_redis(redis)
    auth_deps.bind_redis(redis)
```

（`ensure_seed_users` 必须在 `init_db` 之后——users 表要先存在；`auth_service.bind_redis` 与 `auth_deps.bind_redis` 必须在 `create_client` 之后，两者共用同一个 client。）

在 `app = FastAPI(...)` 那一行之后紧接着加：

```python
app.include_router(auth_router)
```

- [ ] **Step 3: `_card()` 增加 uploader**

替换 `_card`：

```python
def _card(v: dict) -> dict:
    uploader = ({"id": v["uploader_id"], "username": v.get("uploader_username")}
                if v.get("uploader_id") else None)
    return {
        "id": v["id"],
        "title": v["title"],
        "description": v["description"],
        "status": v["status"],
        "duration_sec": v["duration_sec"],
        "thumbnail_url": f"/media/{v['id']}/thumbnail.jpg"
                         if v["status"] == "ready" else None,
        "uploader": uploader,
        "created_at": v["created_at"],
    }
```

`uploader` 为 `None` 表示历史匿名视频（规格 §1.2），前端显示「匿名」。

- [ ] **Step 4: upload-url 加 creator 权限并记录归属**

替换该端点：

```python
@app.post("/api/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(req: UploadUrlRequest,
                            user: CurrentUser = Depends(require_role("creator"))):
    try:
        return presign.issue(req.filename, req.size, user.id)
    except PresignError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

`POST /api/upload/{token}` **完全不改**：它不带 JWT，预签名 token 本身就是凭证（规格 §4.3）。

- [ ] **Step 5: create_video 加权限、归属校验与 uploader_id**

替换该端点：

```python
@app.post("/api/videos")
async def create_video(req: VideoCreateRequest,
                       user: CurrentUser = Depends(require_role("creator"))):
    video_id = req.video_id
    ext = ext_of(req.filename)
    if ext not in config.allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported extension .{ext}")

    # The pre-signed URL was issued to exactly one user; refuse to let anyone
    # else register the video it produced (spec 4.3).
    if not presign.claim_owner(video_id, user.id):
        raise HTTPException(
            status_code=403, detail="This upload token was not issued to you")

    original_path = os.path.join(config.original_dir, video_id, f"original.{ext}")
    if not os.path.exists(original_path):
        raise HTTPException(
            status_code=400,
            detail="Binary not found; finish the upload first",
        )

    await database.insert_video(video_id, req.title, req.description,
                                original_path, uploader_id=user.id)
    await push_task(redis, {"video_id": video_id, "original_path": original_path})
    logger.info("video %s queued for transcoding (uploader %s)", video_id, user.id)
    return {"video_id": video_id, "status": "pending"}
```

归属校验放在二进制存在性检查**之前**：先判权限再判资源，避免向冒名者泄露「该 video_id 是否已上传」的信息。

注意 `claim_owner` 是一次性消费——校验失败或后续步骤失败都不会残留可重用的映射。若上传成功但 `create_video` 因 400（扩展名非法）失败，该 video_id 的归属已被消费，用户需重新走一遍预签名流程，这是可接受的（前端不会构造出这种请求）。

- [ ] **Step 6: 新增 `/api/videos/mine`（必须在 `/{video_id}` 之前）**

在 `list_videos` 端点**之前**插入：

```python
@app.get("/api/videos/mine")
async def my_videos(user: CurrentUser = Depends(require_role("creator"))):
    """Own uploads, failed ones included (spec 4.2).

    Declared BEFORE /api/videos/{video_id} so the literal segment is not
    swallowed by the path parameter.
    """
    rows = await database.list_videos_by_uploader(user.id)
    return {"videos": [_card(v) for v in rows]}
```

改完后端点声明顺序必须是：`/api/health` → `/api/upload-url` → `/api/upload/{token}` → `/api/videos` (POST) → `/api/videos` (GET) → **`/api/videos/mine`** → `/api/videos/{video_id}` → `/api/videos/{video_id}/retry` → `/api/stats`。

- [ ] **Step 7: retry 加归属/角色校验**

替换该端点：

```python
@app.post("/api/videos/{video_id}/retry")
async def retry_video(video_id: str,
                      user: CurrentUser = Depends(get_current_user)):
    v = await database.get_video(video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")

    is_owner = v.get("uploader_id") == user.id
    is_staff = (security.ROLE_LEVEL.get(user.role, 0)
                >= security.ROLE_LEVEL["moderator"])
    if not (is_owner or is_staff):
        raise HTTPException(status_code=403, detail="Not your video")

    if v["status"] != "failed":
        raise HTTPException(
            status_code=400, detail=f"Only failed videos can be retried (current: {v['status']})")
    if not v["original_path"] or not os.path.exists(v["original_path"]):
        raise HTTPException(status_code=400, detail="Original binary is missing")

    await database.set_video_status(video_id, "pending")
    await push_task(redis, {"video_id": video_id, "original_path": v["original_path"]})
    logger.info("video %s re-queued for transcoding by %s", video_id, user.id)
    return {"video_id": video_id, "status": "pending"}
```

匿名历史视频（`uploader_id IS NULL`）任何普通用户都无法重试，只有 moderator+ 可以——`is_owner` 为 `False`（`None != user.id`）。

- [ ] **Step 8: stats 收紧为 moderator+**

替换该端点签名（函数体不变）：

```python
@app.get("/api/stats")
async def stats(_: CurrentUser = Depends(require_role("moderator"))):
```

`GET /api/videos`、`GET /api/videos/{video_id}`、`GET /api/health` 保持公开，不加任何依赖。

- [ ] **Step 9: 语法检查**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe -m py_compile app/presign.py app/server.py; Write-Output "exit=$LASTEXITCODE"
```

Expected: `exit=0`

- [ ] **Step 10: 验证 presign 归属逻辑与端点顺序**

创建临时脚本 `youtube-system/_verify_presign.py`：

```python
"""Temporary check: presign ownership + /api/videos/mine route ordering."""
from app import presign
from app.server import app

# --- ownership ---
p1 = presign.issue("a.mp4", 1024, "userA")
p2 = presign.issue("b.mp4", 1024, "userB")

info = presign.consume(p1["token"])
assert info["video_id"] == p1["video_id"] and info["user_id"] == "userA", info
assert presign.consume(p1["token"]) is None, "token must be single-use"

assert presign.claim_owner(p1["video_id"], "userA") is True
assert presign.claim_owner(p1["video_id"], "userA") is False, "one-shot"
assert presign.claim_owner(p2["video_id"], "userA") is False, "not consumed yet"

presign.consume(p2["token"])
assert presign.claim_owner(p2["video_id"], "userA") is False, "wrong owner"
assert presign.claim_owner(p2["video_id"], "userB") is True

assert presign.consume("bogus-token") is None
assert presign.claim_owner("nosuchvideo", "userA") is False

# --- route ordering ---
paths = [r.path for r in app.routes if r.path.startswith("/api/videos")]
assert "/api/videos/mine" in paths, paths
assert paths.index("/api/videos/mine") < paths.index("/api/videos/{video_id}"), paths

all_paths = [r.path for r in app.routes if r.path.startswith("/api/")]
for expected in ("/api/health", "/api/upload-url", "/api/upload/{token}",
                 "/api/videos", "/api/videos/mine", "/api/videos/{video_id}",
                 "/api/videos/{video_id}/retry", "/api/stats",
                 "/api/auth/login", "/api/auth/register", "/api/auth/refresh",
                 "/api/auth/logout", "/api/auth/me", "/api/users"):
    assert expected in all_paths, f"missing {expected}"

print("PRESIGN_VERIFY_OK")
```

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; ..\venv\Scripts\python.exe _verify_presign.py; Remove-Item _verify_presign.py -Force -ErrorAction SilentlyContinue
```

Expected: `PRESIGN_VERIFY_OK`

导入 `app.server` 会执行 `logging.basicConfig` 但不启动服务，安全。

---

## Task 7: 部署变更 + 后端端到端验证

**Files:**
- Modify: `youtube-system/docker-compose.yml`
- Create（临时，验证后删除）: `youtube-system/test_auth_e2e.py`

- [ ] **Step 1: compose 增加认证环境变量**

在 `docker-compose.yml` 的 `api-server.environment` 中，`TRANSCODED_DIR: data/transcoded` 之后追加三行：

```yaml
      JWT_SECRET: "dev-only-secret-change-in-production"
      ACCESS_TOKEN_TTL: "900"
      REFRESH_TOKEN_TTL: "604800"
      BAN_MARKER_TTL: "86400"
```

改完后 `api-server.environment` 应为 8 个键：`REDIS_URL, DB_PATH, ORIGINAL_DIR, TRANSCODED_DIR, JWT_SECRET, ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL, BAN_MARKER_TTL`。

`transcoder-worker` / `cdn` / `frontend` / `redis` 四个服务**不需要任何改动**（worker 不参与认证，媒体仍公开）。

- [ ] **Step 2: 重建并重启 api-server**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose build api-server; docker compose up -d
```

用 `is_background=true` 启动，再用 `GetTerminalOutput`（`wait_seconds=60`，必要时重复）轮询到出现 `Built` / `Started`。

Expected: 镜像重建成功（会安装 PyJWT + bcrypt），5 个容器全部 `Up`。

- [ ] **Step 3: 确认迁移与种子账号已生效**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose logs api-server --tail 30
```

Expected: 日志中出现 `Seeded admin account 'admin'`、`Seeded creator account 'creator'`、（若 data/ 里有上一轮的库）`Migrated videos: added uploader_id column`、`Database initialized`、`API server started`。

- [ ] **Step 4: 写端到端脚本**

创建 `youtube-system/test_auth_e2e.py`，覆盖规格 §8.1 全部 12 项：

```python
"""End-to-end verification of the user/auth subsystem (spec section 8.1).

Run against a live `docker compose up` stack. Deleted once it passes, matching
the previous round's test_e2e.py convention.
"""
import os
import sqlite3
import subprocess
import sys
import time

import requests

API = "http://localhost:8000"
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "youtube.db")
VIDEO = os.path.join(HERE, "test_video.mp4")
CORRUPT = os.path.join(HERE, "test_corrupt.mp4")
WORKER = "youtube-system-transcoder-worker-1"
LEGACY_ID = "legacy00000001"

passed, failed = [], []


def check(name, cond, extra=""):
    (passed if cond else failed).append(name)
    mark = "PASS" if cond else "FAIL"
    suffix = f"  :: {extra}" if (extra and not cond) else ""
    print(f"  [{mark}] {name}{suffix}")


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def gen_media():
    """A real 3s 720p clip (transcodes OK) and a corrupt file (must fail)."""
    if not os.path.exists(VIDEO):
        subprocess.run(["docker", "exec", WORKER, "ffmpeg", "-f", "lavfi", "-i",
                        "testsrc=duration=3:size=1280x720:rate=30",
                        "-pix_fmt", "yuv420p", "-y", "/tmp/t.mp4"],
                       check=True, capture_output=True)
        subprocess.run(["docker", "cp", f"{WORKER}:/tmp/t.mp4", VIDEO],
                       check=True, capture_output=True)
    with open(CORRUPT, "wb") as f:
        f.write(b"this is definitely not a video file")


def make_legacy_video():
    """Insert an anonymous video straight into the bind-mounted SQLite file so
    spec 8.1 item 6 can be checked even on a fresh database."""
    db = sqlite3.connect(DB, timeout=30)
    t = time.time()
    db.execute("""INSERT OR IGNORE INTO videos
                  (id, title, description, status, uploader_id, created_at, updated_at)
                  VALUES (?, 'Legacy anonymous', 'pre-user-system row', 'ready',
                          NULL, ?, ?)""", (LEGACY_ID, t, t))
    db.commit()
    db.close()


def upload(tok, path, filename):
    """Full pre-sign -> binary -> register flow. Returns (status, video_id)."""
    size = os.path.getsize(path)
    r = requests.post(f"{API}/api/upload-url", headers=hdr(tok),
                      json={"filename": filename, "size": size,
                            "content_type": "video/mp4"})
    if r.status_code != 200:
        return r.status_code, None, r.text
    ps = r.json()
    with open(path, "rb") as f:
        r2 = requests.post(f"{API}{ps['upload_path']}?filename={filename}",
                           data=f, headers={"Content-Type": "application/octet-stream"})
    if r2.status_code != 200:
        return r2.status_code, ps["video_id"], r2.text
    return 200, ps["video_id"], ps


def register(username, email, password="Passw0rd!"):
    return requests.post(f"{API}/api/auth/register", json={
        "username": username, "email": email, "password": password})


def login(email, password="Passw0rd!"):
    r = requests.post(f"{API}/api/auth/login",
                      json={"email": email, "password": password})
    return r, (r.json() if r.status_code == 200 else {})


def wait_status(video_id, tok, want, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = requests.get(f"{API}/api/videos/{video_id}", headers=hdr(tok)).json()
        if v.get("status") == want:
            return v
        time.sleep(3)
    return v


def main():
    gen_media()
    make_legacy_video()
    S = str(int(time.time()))[-6:]
    A = f"alice{S}"
    A_EMAIL = f"alice{S}@t.local"

    print("\n[1] register + conflict handling")
    r = register(A, A_EMAIL)
    check("register -> 201", r.status_code == 201, r.text)
    body = r.json() if r.status_code == 201 else {}
    alice = body.get("user", {})
    check("register body carries no tokens",
          "access_token" not in body and "refresh_token" not in body, body)
    check("new account role is 'user'", alice.get("role") == "user", alice)
    check("email was lowercased", alice.get("email") == A_EMAIL, alice)
    check("duplicate username -> 409",
          register(A, f"other{S}@t.local").status_code == 409)
    check("duplicate email -> 409",
          register(f"bob{S}", A_EMAIL).status_code == 409)
    check("weak password -> 422",
          register(f"weak{S}", f"weak{S}@t.local", "short").status_code == 422)
    check("bad username charset -> 422",
          register(f"bad name{S}", f"bad{S}@t.local").status_code == 422)

    print("\n[2] login")
    r, alice_tok = login(A_EMAIL)
    check("login -> 200", r.status_code == 200, r.text)
    check("token pair shape",
          all(k in alice_tok for k in
              ("access_token", "refresh_token", "token_type", "expires_in", "user")),
          list(alice_tok))
    check("token_type == bearer", alice_tok.get("token_type") == "bearer")
    check("expires_in == 900", alice_tok.get("expires_in") == 900, alice_tok.get("expires_in"))
    alice_access = alice_tok["access_token"]
    alice_refresh = alice_tok["refresh_token"]
    r_bad, _ = login(A_EMAIL, "WrongPassword1")
    r_ghost, _ = login(f"nobody{S}@t.local")
    check("wrong password -> 401", r_bad.status_code == 401)
    check("unknown email -> 401", r_ghost.status_code == 401)
    check("both 401s share one message (no enumeration)",
          r_bad.json().get("detail") == r_ghost.json().get("detail"),
          (r_bad.text, r_ghost.text))

    print("\n[3] /api/auth/me")
    r = requests.get(f"{API}/api/auth/me", headers=hdr(alice_access))
    check("me with access -> 200", r.status_code == 200, r.text)
    check("me returns email + status",
          {"email", "status", "role"} <= set(r.json()), r.json())
    check("me without token -> 401",
          requests.get(f"{API}/api/auth/me").status_code == 401)
    check("me with tampered token -> 401",
          requests.get(f"{API}/api/auth/me",
                       headers=hdr(alice_access[:-3] + "abc")).status_code == 401)
    check("me with refresh token as bearer -> 401",
          requests.get(f"{API}/api/auth/me",
                       headers=hdr(alice_refresh)).status_code == 401)

    print("\n[4] role escalation needs a fresh login")
    r = requests.post(f"{API}/api/upload-url", headers=hdr(alice_access),
                      json={"filename": "x.mp4", "size": 1024})
    check("user role -> upload-url 403", r.status_code == 403, r.text)
    check("403 message names the required role",
          "creator" in r.json().get("detail", ""), r.text)
    check("anonymous -> upload-url 401",
          requests.post(f"{API}/api/upload-url",
                        json={"filename": "x.mp4", "size": 1024}).status_code == 401)

    _, admin_tok = login("admin@mytube.local", "Admin@123")
    admin_access = admin_tok["access_token"]
    check("seed admin can log in", bool(admin_access))
    r = requests.patch(f"{API}/api/users/{alice['id']}/role",
                       headers=hdr(admin_access), json={"role": "creator"})
    check("admin promotes alice -> 200", r.status_code == 200, r.text)
    check("promotion reflected in response", r.json().get("role") == "creator", r.text)
    r = requests.post(f"{API}/api/upload-url", headers=hdr(alice_access),
                      json={"filename": "x.mp4", "size": 1024})
    check("OLD access still 403 (role is baked into the JWT)",
          r.status_code == 403, r.text)
    _, alice_tok = login(A_EMAIL)
    alice_access = alice_tok["access_token"]
    r = requests.post(f"{API}/api/upload-url", headers=hdr(alice_access),
                      json={"filename": "x.mp4", "size": 1024})
    check("after re-login -> 200", r.status_code == 200, r.text)

    print("\n[5] authenticated upload -> transcode -> /api/videos/mine")
    st, vid, info = upload(alice_access, VIDEO, "test_video.mp4")
    check("upload flow succeeded", st == 200, info)
    r = requests.post(f"{API}/api/videos", headers=hdr(alice_access), json={
        "video_id": vid, "title": "Alice auth test",
        "description": "e2e", "filename": "test_video.mp4"})
    check("create_video -> 200", r.status_code == 200, r.text)
    r = requests.post(f"{API}/api/videos", headers=hdr(alice_access), json={
        "video_id": vid, "title": "Twice", "description": "", "filename": "test_video.mp4"})
    check("re-registering the same video_id -> 403 (ownership consumed)",
          r.status_code == 403, r.text)
    v = wait_status(vid, alice_access, "ready", timeout=240)
    check("video reached 'ready'", v.get("status") == "ready", v)
    check("detail carries uploader.username",
          (v.get("uploader") or {}).get("username") == A, v.get("uploader"))
    r = requests.get(f"{API}/api/videos/mine", headers=hdr(alice_access))
    check("/api/videos/mine -> 200", r.status_code == 200, r.text)
    mine = r.json().get("videos", []) if r.status_code == 200 else []
    check("mine contains the upload", any(x["id"] == vid for x in mine), [x["id"] for x in mine])
    check("mine card carries uploader",
          all(x.get("uploader", {}).get("username") == A for x in mine), mine)
    check("anonymous -> /api/videos/mine 401",
          requests.get(f"{API}/api/videos/mine").status_code == 401)

    print("\n[6] legacy anonymous video")
    r = requests.get(f"{API}/api/videos/{LEGACY_ID}")
    check("legacy video is public", r.status_code == 200, r.text)
    check("legacy uploader is null",
          r.status_code == 200 and r.json().get("uploader") is None,
          r.text[:200])
    lst = requests.get(f"{API}/api/videos").json().get("videos", [])
    legacy_card = next((x for x in lst if x["id"] == LEGACY_ID), None)
    check("list card also null uploader",
          legacy_card is not None and legacy_card.get("uploader") is None, legacy_card)

    print("\n[7] cross-user pre-sign claim is rejected")
    B = f"bob{S}"
    register(B, f"bob{S}@t.local")
    _, b_tok = login(f"bob{S}@t.local")
    requests.patch(f"{API}/api/users/{b_tok['user']['id']}/role",
                   headers=hdr(admin_access), json={"role": "creator"})
    _, b_tok = login(f"bob{S}@t.local")
    bob_access = b_tok["access_token"]
    st, bob_vid, info = upload(bob_access, VIDEO, "test_video.mp4")
    check("bob uploaded a binary", st == 200, info)
    r = requests.post(f"{API}/api/videos", headers=hdr(alice_access), json={
        "video_id": bob_vid, "title": "Stolen", "description": "",
        "filename": "test_video.mp4"})
    check("alice registering bob's video_id -> 403", r.status_code == 403, r.text)
    r = requests.post(f"{API}/api/videos", headers=hdr(bob_access), json={
        "video_id": bob_vid, "title": "Bob own", "description": "",
        "filename": "test_video.mp4"})
    check("bob registering his own video_id -> 200", r.status_code == 200, r.text)
    r = requests.post(f"{API}/api/videos", headers=hdr(alice_access), json={
        "video_id": "deadbeefdeadbeef", "title": "No presign",
        "description": "", "filename": "test_video.mp4"})
    check("unknown video_id -> 403", r.status_code == 403, r.text)

    print("\n[8] refresh rotation + replay defence")
    C = f"carol{S}"
    register(C, f"carol{S}@t.local")
    _, c_tok = login(f"carol{S}@t.local")
    carol_rt = c_tok["refresh_token"]
    r = requests.post(f"{API}/api/auth/refresh", json={"refresh_token": carol_rt})
    check("refresh -> 200", r.status_code == 200, r.text)
    c2 = r.json() if r.status_code == 200 else {}
    check("refresh rotated the token",
          c2.get("refresh_token") and c2["refresh_token"] != carol_rt, c2)
    check("refresh returns a new access token", bool(c2.get("access_token")))
    r = requests.post(f"{API}/api/auth/refresh", json={"refresh_token": carol_rt})
    check("replaying the OLD refresh -> 401", r.status_code == 401, r.text)
    r = requests.post(f"{API}/api/auth/refresh",
                      json={"refresh_token": c2.get("refresh_token", "")})
    check("replay revoked the NEW token too", r.status_code == 401, r.text)
    check("malformed refresh token -> 401",
          requests.post(f"{API}/api/auth/refresh",
                        json={"refresh_token": "no-separator-value-here"}).status_code == 401)

    print("\n[9] logout")
    _, c_tok = login(f"carol{S}@t.local")
    carol_access, carol_rt = c_tok["access_token"], c_tok["refresh_token"]
    r = requests.post(f"{API}/api/auth/logout", headers=hdr(carol_access))
    check("logout -> 204", r.status_code == 204, r.text)
    check("refresh after logout -> 401",
          requests.post(f"{API}/api/auth/refresh",
                        json={"refresh_token": carol_rt}).status_code == 401)
    check("logout without token -> 401",
          requests.post(f"{API}/api/auth/logout").status_code == 401)

    print("\n[10] failed transcode + retry ownership")
    st, bad_vid, info = upload(alice_access, CORRUPT, "test_corrupt.mp4")
    check("corrupt binary uploaded", st == 200, info)
    r = requests.post(f"{API}/api/videos", headers=hdr(alice_access), json={
        "video_id": bad_vid, "title": "Corrupt", "description": "",
        "filename": "test_corrupt.mp4"})
    check("corrupt video registered", r.status_code == 200, r.text)
    v = wait_status(bad_vid, alice_access, "failed", timeout=120)
    check("corrupt video -> failed", v.get("status") == "failed", v)
    check("failed carries error_msg", bool(v.get("error_msg")), v)
    E = f"erin{S}"
    register(E, f"erin{S}@t.local")
    _, e_tok = login(f"erin{S}@t.local")
    erin_access = e_tok["access_token"]
    r = requests.post(f"{API}/api/videos/{bad_vid}/retry", headers=hdr(erin_access))
    check("plain user retrying someone else's video -> 403",
          r.status_code == 403, r.text)
    r = requests.post(f"{API}/api/videos/{bad_vid}/retry", headers=hdr(bob_access))
    check("creator retrying another creator's video -> 403",
          r.status_code == 403, r.text)
    r = requests.post(f"{API}/api/videos/{bad_vid}/retry")
    check("anonymous retry -> 401", r.status_code == 401)
    r = requests.post(f"{API}/api/videos/{bad_vid}/retry", headers=hdr(alice_access))
    check("owner retry -> 200", r.status_code == 200, r.text)
    # Deliberately targets `vid` (already 'ready', owned by alice), NOT
    # bad_vid: the retry above put bad_vid back to 'pending' and the worker
    # may flip it to 'failed' again within milliseconds, which would make a
    # second retry return 200 and the assertion flaky.
    r = requests.post(f"{API}/api/videos/{vid}/retry", headers=hdr(alice_access))
    check("retrying a non-failed video -> 400", r.status_code == 400, r.text)

    print("\n[11] permission matrix (spec 4.5)")
    requests.patch(f"{API}/api/users/{c_tok['user']['id']}/role",
                   headers=hdr(admin_access), json={"role": "moderator"})
    _, c_tok = login(f"carol{S}@t.local")
    carol_access = c_tok["access_token"]
    check("anonymous GET /api/videos -> 200",
          requests.get(f"{API}/api/videos").status_code == 200)
    check("anonymous GET /api/videos/{id} -> 200",
          requests.get(f"{API}/api/videos/{vid}").status_code == 200)
    check("anonymous GET /api/users/{id} -> 200",
          requests.get(f"{API}/api/users/{alice['id']}").status_code == 200)
    pub = requests.get(f"{API}/api/users/{alice['id']}").json()
    check("public user projection hides email/status",
          set(pub) == {"id", "username", "role"}, pub)
    check("user role -> upload-url 403",
          requests.post(f"{API}/api/upload-url", headers=hdr(erin_access),
                        json={"filename": "x.mp4", "size": 1024}).status_code == 403)
    check("creator -> upload-url 200",
          requests.post(f"{API}/api/upload-url", headers=hdr(alice_access),
                        json={"filename": "x.mp4", "size": 1024}).status_code == 200)
    check("moderator -> upload-url 200 (role inclusion)",
          requests.post(f"{API}/api/upload-url", headers=hdr(carol_access),
                        json={"filename": "x.mp4", "size": 1024}).status_code == 200)
    check("user -> stats 403",
          requests.get(f"{API}/api/stats", headers=hdr(erin_access)).status_code == 403)
    check("creator -> stats 403",
          requests.get(f"{API}/api/stats", headers=hdr(alice_access)).status_code == 403)
    check("moderator -> stats 200",
          requests.get(f"{API}/api/stats", headers=hdr(carol_access)).status_code == 200)
    check("anonymous -> stats 401",
          requests.get(f"{API}/api/stats").status_code == 401)
    check("moderator -> list users 403 (admin only)",
          requests.get(f"{API}/api/users", headers=hdr(carol_access)).status_code == 403)
    check("admin -> list users 200",
          requests.get(f"{API}/api/users", headers=hdr(admin_access)).status_code == 200)
    users_body = requests.get(f"{API}/api/users", headers=hdr(admin_access)).json()
    check("list users shape", {"users", "total"} <= set(users_body), list(users_body))
    check("total >= 6 (2 seeds + 4 test users registered before this point)",
          users_body.get("total", 0) >= 6, users_body.get("total"))
    check("limit is capped at 100 (le=100 -> 422)",
          requests.get(f"{API}/api/users?limit=500",
                       headers=hdr(admin_access)).status_code == 422)
    # The legacy video is 'ready', so a moderator can only ever get 400 here.
    # That 400 is the proof we need: a 403 would mean the is_staff bypass in
    # the retry handler is missing (carol does not own LEGACY_ID).
    check("moderator passes the retry ownership gate (-> 400, it is 'ready')",
          requests.post(f"{API}/api/videos/{LEGACY_ID}/retry",
                        headers=hdr(carol_access)).status_code == 400,
          "403 would mean the moderator bypass is missing")

    print("\n[12] admin self-protection + illegal values")
    check("admin changes own role -> 400",
          requests.patch(f"{API}/api/users/{admin_tok['user']['id']}/role",
                         headers=hdr(admin_access),
                         json={"role": "user"}).status_code == 400)
    check("admin bans self -> 400",
          requests.post(f"{API}/api/users/{admin_tok['user']['id']}/ban",
                        headers=hdr(admin_access), json={}).status_code == 400)
    check("illegal role value -> 400",
          requests.patch(f"{API}/api/users/{alice['id']}/role",
                         headers=hdr(admin_access),
                         json={"role": "superuser"}).status_code == 400)
    check("role change on missing user -> 404",
          requests.patch(f"{API}/api/users/nosuchuser/role",
                         headers=hdr(admin_access),
                         json={"role": "user"}).status_code == 404)
    check("non-admin role change -> 403",
          requests.patch(f"{API}/api/users/{alice['id']}/role",
                         headers=hdr(erin_access),
                         json={"role": "admin"}).status_code == 403)

    print("\n[13] ban takes effect (spec 2.5)")
    D = f"dave{S}"
    register(D, f"dave{S}@t.local")
    _, d_tok = login(f"dave{S}@t.local")
    dave_access, dave_rt = d_tok["access_token"], d_tok["refresh_token"]
    dave_id = d_tok["user"]["id"]
    r = requests.post(f"{API}/api/users/{dave_id}/ban",
                      headers=hdr(admin_access), json={"reason": "spam"})
    check("ban -> 200 with status banned",
          r.status_code == 200 and r.json().get("status") == "banned", r.text)
    check("banned user login -> 403",
          login(f"dave{S}@t.local")[0].status_code == 403)
    check("banned 403 message",
          login(f"dave{S}@t.local")[0].json().get("detail") == "account is banned")
    check("banned user's refresh -> 401",
          requests.post(f"{API}/api/auth/refresh",
                        json={"refresh_token": dave_rt}).status_code == 401)
    check("HELD access immediately 403 (ban marker checked per request, spec 2.5)",
          requests.get(f"{API}/api/auth/me",
                       headers=hdr(dave_access)).status_code == 403)
    r = requests.post(f"{API}/api/users/{dave_id}/unban", headers=hdr(admin_access))
    check("unban -> 200 with status active",
          r.status_code == 200 and r.json().get("status") == "active", r.text)
    check("unbanned user can log in again",
          login(f"dave{S}@t.local")[0].status_code == 200)

    print("\n[14] public endpoints unchanged")
    check("/api/health is public",
          requests.get(f"{API}/api/health").status_code == 200)
    check("upload with a bogus token -> 403",
          requests.post(f"{API}/api/upload/bogus?filename=x.mp4",
                        data=b"x").status_code == 403)

    print(f"\n{'=' * 60}\nPASSED {len(passed)}   FAILED {len(failed)}")
    if failed:
        print("Failures:")
        for name in failed:
            print(f"  - {name}")
    print("=" * 60)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行端到端验证**

Run（后台执行，转码需 1–3 分钟）：

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; D:\StudyProjects\system-design-notes\venv\Scripts\python.exe test_auth_e2e.py
```

Expected 结尾：`PASSED <N>   FAILED 0`，退出码 0。

- [ ] **Step 6: 失败时按 systematic-debugging 定位**

常见根因对照（先读 `docker compose logs api-server --tail 50`，不要凭猜测改代码）：

| 症状 | 根因 |
|------|------|
| 全部请求 `ConnectionError` | 容器没起来，`docker compose ps` 查状态 |
| 注册 500 `no such table: users` | `init_db()` 的 users 建表语句没进 `executescript` |
| 注册 500 `no such column: uploader_id` | Step 1 的 PRAGMA 迁移分支没执行；`docker compose logs` 应有 `Migrated videos` |
| 登录 401（种子账号） | `ensure_seed_users()` 未在 lifespan 调用，或 compose 未重建镜像 |
| refresh 500 `'NoneType' object has no attribute 'get'` | `bind_redis()` 未调用 |
| `/api/videos/mine` 404 或返回单个视频详情 | 路由顺序错误，`/mine` 被 `/{video_id}` 吞掉 |
| 第 [7] 组 403 失败（返回 200） | `claim_owner` 未接入或 `consume` 未写 `_owners` |
| 第 [5] 组一直等不到 ready | worker 未起或转码失败，看 `docker compose logs transcoder-worker --tail 50` |
| 422 而非预期 400/403 | Pydantic 字段约束过严（尤其 `LoginRequest.password` 的 min_length 必须是 1） |
| `make_legacy_video` 报 `database is locked` | api-server 正在写库。脚本已设 `timeout=30`，通常等一会就好；直接重跑脚本即可（`INSERT OR IGNORE` 幂等） |
| 第 [10] 组「retrying a non-failed video」偶发失败 | 说明该断言被改回了 `bad_vid`。必须打在 `vid`（已 ready）上，`bad_vid` 会被 worker 重新置为 failed，产生竞态 |

修完重跑整个脚本（脚本对用户名加时间戳后缀，可重复执行；`make_legacy_video` 用 `INSERT OR IGNORE`，也幂等）。

- [ ] **Step 7: 清理**

全部通过后删除脚本与生成的媒体文件：

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Remove-Item test_auth_e2e.py, test_video.mp4, test_corrupt.mp4 -Force -ErrorAction SilentlyContinue; Write-Output "cleaned"
```

Expected: `cleaned`

注意：验证过程会在数据库里留下若干测试用户与测试视频。**不要**删除 `data/youtube.db`（里面有上一轮的真实视频），但可用 admin 账号在前端 `/admin/users` 页面确认测试用户可见（Task 13 的人工验证会用到）。

---

## Task 8: 前端基础模块——tokens.js / api.js / auth.js

**Files:**
- Create: `youtube-system/frontend/src/tokens.js`
- Modify: `youtube-system/frontend/src/api.js`（整体重写，现 44 行）
- Create: `youtube-system/frontend/src/auth.js`

依赖方向严格单向，无循环 import：

```
tokens.js  ←  api.js  ←  auth.js  ←  router.js / views
                  ↑                      ↑
                  └──── main.js ─────────┘
```

- [ ] **Step 1: 写 tokens.js**

```js
/**
 * Raw localStorage access for the two tokens.
 *
 * Split out from auth.js so api.js (whose interceptors must read and clear
 * tokens) never has to import auth.js - that would be a circular import.
 */
const ACCESS_KEY = 'mytube_access'
const REFRESH_KEY = 'mytube_refresh'

export function getAccess() {
  return localStorage.getItem(ACCESS_KEY)
}

export function getRefresh() {
  return localStorage.getItem(REFRESH_KEY)
}

export function setTokens(access, refresh) {
  localStorage.setItem(ACCESS_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}
```

- [ ] **Step 2: 重写 api.js**

保留现有 7 个视频相关函数的签名不变（HomeView/UploadView/WatchView 正在用），在其前后加入拦截器与认证接口：

```js
import axios from 'axios'
import { clearTokens, getAccess, getRefresh, setTokens } from './tokens'

const http = axios.create({ baseURL: '', timeout: 0 })

/**
 * Session-failure hook, installed by main.js. Kept as an injected callback so
 * this module does not have to import the router (which imports auth -> api).
 */
let authFailureHandler = null
export function setAuthFailureHandler(fn) {
  authFailureHandler = fn
}

/** Uniform error text extraction: FastAPI puts the message in `detail`. */
export function extractError(e, fallback = 'Request failed') {
  return e?.response?.data?.detail || e?.message || fallback
}

// ---- request: attach the bearer token when we have one ----
http.interceptors.request.use((cfg) => {
  const token = getAccess()
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// ---- response: single-flight refresh on 401, then replay the request once ----
let refreshing = null

function isAuthCall(cfg) {
  const url = cfg?.url || ''
  return url.includes('/api/auth/login') || url.includes('/api/auth/refresh')
}

function pathOf(cfg) {
  const url = cfg?.url || '/'
  return url.startsWith('/') ? url.split('?')[0] : '/'
}

async function doRefresh() {
  // Bare axios, NOT `http`: going through the instance would recurse into this
  // very interceptor when the refresh itself returns 401.
  const { data } = await axios.post('/api/auth/refresh', {
    refresh_token: getRefresh(),
  })
  setTokens(data.access_token, data.refresh_token)
  return data
}

http.interceptors.response.use(
  (res) => res,
  async (error) => {
    const cfg = error.config
    const status = error.response?.status
    if (status !== 401 || !cfg || cfg._retried || isAuthCall(cfg) || !getRefresh()) {
      return Promise.reject(error)
    }
    cfg._retried = true
    try {
      // Shared promise: concurrent 401s must not each rotate the token, since
      // rotation invalidates the previous one and they would revoke each other.
      refreshing = refreshing || doRefresh()
      await refreshing
      refreshing = null
      return await http.request(cfg)
    } catch (refreshError) {
      refreshing = null
      clearTokens()
      if (authFailureHandler) authFailureHandler(pathOf(cfg))
      return Promise.reject(refreshError)
    }
  },
)

// ---- auth ----
export function registerRequest(username, email, password) {
  return http.post('/api/auth/register', { username, email, password })
}

export function loginRequest(email, password) {
  return http.post('/api/auth/login', { email, password })
}

export function meRequest() {
  return http.get('/api/auth/me')
}

export function logoutRequest() {
  return http.post('/api/auth/logout')
}

// ---- users (admin) ----
export function listUsers(limit = 50, offset = 0) {
  return http.get('/api/users', { params: { limit, offset } })
}

export function setUserRole(id, role) {
  return http.patch(`/api/users/${id}/role`, { role })
}

export function banUser(id, reason = '') {
  return http.post(`/api/users/${id}/ban`, { reason })
}

export function unbanUser(id) {
  return http.post(`/api/users/${id}/unban`)
}

// ---- videos ----
export function getUploadUrl(filename, size, contentType = 'video/mp4') {
  return http.post('/api/upload-url', {
    filename,
    size,
    content_type: contentType,
  })
}

export function uploadBinary(uploadPath, file, onProgress) {
  return http.post(`${uploadPath}?filename=${encodeURIComponent(file.name)}`, file, {
    headers: { 'Content-Type': 'application/octet-stream' },
    onUploadProgress: (e) => onProgress && onProgress(e),
  })
}

export function createVideo(videoId, title, description, filename) {
  return http.post('/api/videos', {
    video_id: videoId,
    title,
    description,
    filename,
  })
}

export function listVideos() {
  return http.get('/api/videos')
}

export function listMyVideos() {
  return http.get('/api/videos/mine')
}

export function getVideo(id) {
  return http.get(`/api/videos/${id}`)
}

export function retryVideo(id) {
  return http.post(`/api/videos/${id}/retry`)
}

export function getStats() {
  return http.get('/api/stats')
}
```

- [ ] **Step 3: 写 auth.js**

```js
import { reactive } from 'vue'
import { loginRequest, logoutRequest, meRequest, registerRequest } from './api'
import { clearTokens, getAccess, getRefresh, setTokens } from './tokens'

// Re-exported so views can import everything auth-related from one place
// (spec 5.1 lists these as auth.js exports).
export { clearTokens, getAccess, getRefresh, setTokens }

/** Must stay in sync with ROLE_LEVEL in app/auth/security.py (spec 1.3). */
export const ROLE_LEVEL = { user: 1, creator: 2, moderator: 3, admin: 4 }

export const authState = reactive({ user: null, ready: false })

export function hasRole(minRole) {
  const user = authState.user
  if (!user) return false
  return (ROLE_LEVEL[user.role] || 0) >= (ROLE_LEVEL[minRole] || 0)
}

/**
 * Rebuild the session on page load. An expired access token is transparently
 * renewed by the api.js interceptor, so this only fails when the refresh token
 * is gone too.
 */
export async function restore() {
  if (!getAccess()) {
    authState.ready = true
    return
  }
  try {
    const { data } = await meRequest()
    authState.user = data
  } catch {
    clearTokens()
    authState.user = null
  } finally {
    authState.ready = true
  }
}

export async function login(email, password) {
  const { data } = await loginRequest(email, password)
  setTokens(data.access_token, data.refresh_token)
  authState.user = data.user
  return data
}

/**
 * The register endpoint deliberately returns no tokens, so log in immediately
 * with the same credentials: RegisterView can treat success as "logged in".
 */
export async function register(username, email, password) {
  const { data } = await registerRequest(username, email, password)
  await login(email, password)
  return data.user
}

export async function logout() {
  try {
    await logoutRequest()
  } catch {
    // Token may already be expired - clearing locally is what matters.
  }
  clearTokens()
  authState.user = null
}
```

- [ ] **Step 4: 验证——构建必须成功（此时新模块尚未被引用，仅校验语法）**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system\frontend; npm run build
```

Expected: `vite build` 成功输出 `dist/`。若报解析错误，检查 import 路径与 ESM 语法。

注意：此时 `router.js`/`main.js` 还没引用 `auth.js`，Vite 的 tree-shaking 不会打包它，因此**构建成功不代表模块无误**。真正的接线验证在 Task 9 Step 7。

---

## Task 9: 路由守卫、入口、样式、导航栏

**Files:**
- Modify: `youtube-system/frontend/src/router.js`（整体重写，现 14 行）
- Modify: `youtube-system/frontend/src/main.js`（整体重写，现 7 行）
- Modify: `youtube-system/frontend/src/style.css`（末尾追加）
- Modify: `youtube-system/frontend/src/App.vue`（整体重写，现 12 行）

本任务引用了 Task 10/11 才创建的 4 个视图文件，因此 **Step 1 先创建占位视图**，否则构建会因 import 失败而中断；Task 10/11 再填充真实内容。

- [ ] **Step 1: 创建 4 个占位视图（Task 10/11 会整体覆盖）**

`frontend/src/views/LoginView.vue`、`RegisterView.vue`、`MyVideosView.vue`、`AdminUsersView.vue` 各写入：

```vue
<template>
  <div class="empty-state">Loading…</div>
</template>
```

- [ ] **Step 2: 重写 router.js**

```js
import { createRouter, createWebHistory } from 'vue-router'
import { authState, hasRole } from './auth'
import AdminUsersView from './views/AdminUsersView.vue'
import HomeView from './views/HomeView.vue'
import LoginView from './views/LoginView.vue'
import MyVideosView from './views/MyVideosView.vue'
import RegisterView from './views/RegisterView.vue'
import UploadView from './views/UploadView.vue'
import WatchView from './views/WatchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/login', component: LoginView, meta: { guestOnly: true } },
    { path: '/register', component: RegisterView, meta: { guestOnly: true } },
    {
      path: '/upload',
      component: UploadView,
      // No hard redirect on insufficient role: UploadView renders an inline
      // "requires creator role" message instead (spec 5.3).
      meta: { requiresAuth: true, role: 'creator' },
    },
    { path: '/my-videos', component: MyVideosView, meta: { requiresAuth: true } },
    {
      path: '/admin/users',
      component: AdminUsersView,
      meta: { requiresAuth: true, role: 'admin' },
    },
    { path: '/watch/:id', component: WatchView },
  ],
})

router.beforeEach((to) => {
  const loggedIn = !!authState.user

  if (to.meta.guestOnly && loggedIn) return { path: '/' }

  if (to.meta.requiresAuth && !loggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // Insufficient role: bounce home for the admin panel (do not advertise that
  // it exists), but let /upload through so it can explain itself inline.
  if (to.meta.role && loggedIn && !hasRole(to.meta.role) && to.path !== '/upload') {
    return { path: '/' }
  }

  return true
})

export default router
```

- [ ] **Step 3: 重写 main.js**

```js
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { setAuthFailureHandler } from './api'
import { restore } from './auth'
import './style.css'

// Session expired mid-use: send the user to the login page and remember where
// they were. Injected here (not inside api.js) to keep imports one-directional.
setAuthFailureHandler((path) => {
  router.push({
    path: '/login',
    query: path && path !== '/' ? { redirect: path } : {},
  })
})

// Restore the session before mounting so a page refresh never flashes the
// logged-out navbar. Costs one /api/auth/me round trip on first paint.
restore().finally(() => {
  createApp(App).use(router).mount('#app')
})
```

- [ ] **Step 4: style.css 末尾追加**

在文件末尾（`.rendition-item { … }` 规则之后）追加：

```css
/* ---- Auth & identity (user system) ---- */
.nav-actions { display: flex; align-items: center; gap: 12px; }

.auth-page { max-width: 400px; margin: 48px auto 0; }
.auth-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 28px;
}
.auth-card h2 { margin: 0 0 20px; font-size: 20px; }
.auth-footer { margin-top: 16px; font-size: 13px; color: var(--text-dim); }
.auth-footer a { color: var(--accent); text-decoration: none; }
.auth-footer a:hover { text-decoration: underline; }

.user-menu { position: relative; }
.user-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 18px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text);
  font-size: 14px;
  cursor: pointer;
}
.user-btn:hover { background: var(--bg-hover); }
.user-btn .caret { font-size: 10px; color: var(--text-dim); }

.dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  min-width: 190px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 20;
}
.dropdown-header {
  padding: 8px 10px 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 6px;
}
.dropdown-header .name { font-size: 14px; font-weight: 600; }
.dropdown-header .mail { font-size: 12px; color: var(--text-dim); }
.dropdown-item {
  display: block;
  width: 100%;
  padding: 9px 10px;
  border: none;
  border-radius: 6px;
  background: none;
  color: var(--text);
  font-size: 14px;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}
.dropdown-item:hover { background: var(--bg-hover); }

.role-tag {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  background: #143d5c;
  color: #64b5f6;
}
.role-tag.admin { background: #5c1f1f; color: #e57373; }
.role-tag.moderator { background: #4a3a19; color: #ffd54f; }
.role-tag.creator { background: #1b4a2a; color: #66bb6a; }

.uploader { color: var(--text-dim); font-size: 12px; margin: 2px 0 0; }

.hint-box {
  background: #14303d;
  border: 1px solid #1f4d63;
  color: #8fd3f4;
  padding: 12px 16px;
  border-radius: 8px;
  margin: 12px 0;
  font-size: 13px;
}

/* Admin users table */
.table-wrap { overflow-x: auto; }
table.users {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
table.users th, table.users td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
table.users th { color: var(--text-dim); font-weight: 600; font-size: 12px; }
table.users tr:hover td { background: var(--bg-card); }
table.users select {
  background: var(--bg-card);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 6px;
}
table.users .row-actions { display: flex; gap: 8px; align-items: center; }
.btn.tiny { padding: 4px 10px; font-size: 12px; border-radius: 12px; }
.btn.danger { background: #6b2020; }
.btn.danger:hover { background: #8a2a2a; }
```

- [ ] **Step 5: 重写 App.vue**

```vue
<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { authState, hasRole, logout } from './auth'

const router = useRouter()
const menuOpen = ref(false)
const menuEl = ref(null)

function onDocClick(e) {
  if (menuEl.value && !menuEl.value.contains(e.target)) menuOpen.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

async function signOut() {
  menuOpen.value = false
  await logout()
  router.push('/')
}

function go(path) {
  menuOpen.value = false
  router.push(path)
}
</script>

<template>
  <div class="app">
    <nav class="navbar">
      <RouterLink to="/" class="logo"><span class="play">▶</span> MyTube</RouterLink>

      <div class="nav-actions">
        <RouterLink v-if="hasRole('creator')" to="/upload" class="btn">Upload</RouterLink>

        <template v-if="authState.user">
          <div ref="menuEl" class="user-menu">
            <button class="user-btn" @click="menuOpen = !menuOpen">
              {{ authState.user.username }}<span class="caret">▾</span>
            </button>
            <div v-if="menuOpen" class="dropdown">
              <div class="dropdown-header">
                <div class="name">{{ authState.user.username }}</div>
                <div class="mail">{{ authState.user.email }}</div>
                <span class="role-tag" :class="authState.user.role">
                  {{ authState.user.role }}
                </span>
              </div>
              <button class="dropdown-item" @click="go('/my-videos')">My videos</button>
              <button v-if="hasRole('admin')" class="dropdown-item" @click="go('/admin/users')">
                Admin panel
              </button>
              <button class="dropdown-item" @click="signOut">Sign out</button>
            </div>
          </div>
        </template>

        <template v-else-if="authState.ready">
          <RouterLink to="/login" class="btn secondary">Login</RouterLink>
          <RouterLink to="/register" class="btn">Register</RouterLink>
        </template>
      </div>
    </nav>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>
```

`v-else-if="authState.ready"` 是必要的：`restore()` 完成前 `user` 为 `null`，若无此条件会在首屏闪一下 Login/Register 按钮。

- [ ] **Step 6: 构建 + 部署验证**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose build frontend; docker compose up -d frontend
```

用 `is_background=true` 启动，再用 `GetTerminalOutput`（`wait_seconds=120`，必要时重复）轮询到构建结束。

Expected: 构建成功，`frontend` 容器重启。

- [ ] **Step 7: 冒烟验证（浏览器）**

打开 `http://localhost:8080`，检查：

1. 导航栏右侧出现 **Login** / **Register** 按钮（未登录态），**没有** Upload 按钮
2. 点击 Login → 跳到 `/login`，页面显示占位 `Loading…`（Task 10 才填充）
3. 直接访问 `http://localhost:8080/my-videos` → 被重定向到 `/login?redirect=/my-videos`（**守卫已生效**）
4. 直接访问 `http://localhost:8080/admin/users` → 同样重定向到登录页
5. 直接访问 `http://localhost:8080/upload` → 重定向到 `/login?redirect=/upload`
6. 首页视频列表正常加载（公开端点未被破坏），浏览器控制台无红色报错

第 3–5 项通过即证明 `main.js` 的 `restore()` → `router.beforeEach` 链路已接通。

---

## Task 10: LoginView + RegisterView

**Files:**
- Modify: `youtube-system/frontend/src/views/LoginView.vue`（覆盖 Task 9 的占位）
- Modify: `youtube-system/frontend/src/views/RegisterView.vue`（同上）

- [ ] **Step 1: 写 LoginView.vue**

```vue
<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { extractError } from '../api'
import { login } from '../auth'

const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (!email.value.trim() || !password.value) {
    error.value = 'Email and password are required'
    return
  }
  busy.value = true
  try {
    await login(email.value.trim(), password.value)
    // Honour ?redirect= so the guard sends users back where they came from.
    const redirect = route.query.redirect
    router.push(typeof redirect === 'string' && redirect.startsWith('/') ? redirect : '/')
  } catch (e) {
    error.value = extractError(e, 'Login failed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>Sign in to MyTube</h2>

      <div class="field">
        <label>Email</label>
        <input
          v-model="email"
          type="email"
          placeholder="you@example.com"
          autocomplete="username"
          @keyup.enter="submit"
        />
      </div>

      <div class="field">
        <label>Password</label>
        <input
          v-model="password"
          type="password"
          placeholder="Your password"
          autocomplete="current-password"
          @keyup.enter="submit"
        />
      </div>

      <div v-if="error" class="error-box">{{ error }}</div>

      <button class="btn" style="width: 100%" :disabled="busy" @click="submit">
        {{ busy ? 'Signing in…' : 'Sign in' }}
      </button>

      <p class="auth-footer">
        No account? <RouterLink to="/register">Register</RouterLink>
      </p>
      <p class="auth-footer">
        Local test accounts: <code>admin@mytube.local / Admin@123</code> ·
        <code>creator@mytube.local / Creator@123</code>
      </p>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 写 RegisterView.vue**

```vue
<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { extractError } from '../api'
import { register } from '../auth'

const router = useRouter()
const username = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const busy = ref(false)

// Mirror the backend rules (spec 4.4) so users get feedback before a round trip.
const usernameHint = computed(() => {
  const v = username.value
  if (!v) return ''
  if (v.length < 3 || v.length > 32) return 'Username must be 3-32 characters'
  if (!/^[a-zA-Z0-9_]+$/.test(v)) return 'Only letters, digits and underscore'
  return ''
})
const passwordHint = computed(() => {
  if (!password.value) return ''
  if (password.value.length < 8) return 'At least 8 characters'
  if (password.value.length > 72) return 'At most 72 characters'
  return ''
})
const mismatch = computed(() => !!confirm.value && confirm.value !== password.value)
const canSubmit = computed(() =>
  !!username.value && !!email.value && !!password.value &&
  !usernameHint.value && !passwordHint.value && !mismatch.value)

async function submit() {
  error.value = ''
  if (!canSubmit.value) {
    error.value = mismatch.value ? 'Passwords do not match' : 'Please fix the fields above'
    return
  }
  busy.value = true
  try {
    // register() logs in automatically, so we land on the home page signed in.
    await register(username.value.trim(), email.value.trim().toLowerCase(), password.value)
    router.push('/')
  } catch (e) {
    error.value = extractError(e, 'Registration failed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>Create your account</h2>

      <div class="field">
        <label>Username</label>
        <input v-model="username" placeholder="alice_01" autocomplete="username" />
        <small v-if="usernameHint" style="color: var(--accent)">{{ usernameHint }}</small>
      </div>

      <div class="field">
        <label>Email</label>
        <input v-model="email" type="email" placeholder="you@example.com" />
      </div>

      <div class="field">
        <label>Password</label>
        <input v-model="password" type="password" placeholder="At least 8 characters"
               autocomplete="new-password" />
        <small v-if="passwordHint" style="color: var(--accent)">{{ passwordHint }}</small>
      </div>

      <div class="field">
        <label>Confirm password</label>
        <input v-model="confirm" type="password" autocomplete="new-password"
               @keyup.enter="submit" />
        <small v-if="mismatch" style="color: var(--accent)">Passwords do not match</small>
      </div>

      <div v-if="error" class="error-box">{{ error }}</div>

      <button class="btn" style="width: 100%" :disabled="busy || !canSubmit" @click="submit">
        {{ busy ? 'Creating…' : 'Register' }}
      </button>

      <p class="auth-footer">
        Already have an account? <RouterLink to="/login">Sign in</RouterLink>
      </p>
      <p class="auth-footer" style="font-size: 12px">
        New accounts get the <span class="role-tag">user</span> role and cannot upload
        until an admin promotes them to <span class="role-tag creator">creator</span>.
      </p>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 构建部署**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose build frontend; docker compose up -d frontend
```

后台执行 + `GetTerminalOutput` 轮询到完成。

- [ ] **Step 4: 浏览器验证**

1. `http://localhost:8080/register` → 注册 `tester1` / `tester1@t.local` / `Passw0rd!`
   - 期望：跳回首页，导航栏显示 `tester1 ▾`，下拉里显示邮箱与 `user` 角色标签
   - 期望：**没有** Upload 按钮（user 角色）
2. 用户名输入 `ab` → 下方出现红字 `Username must be 3-32 characters`，Register 按钮禁用
3. 用户名输入 `bad name` → 红字 `Only letters, digits and underscore`
4. 密码输入 `short` → 红字 `At least 8 characters`
5. 两次密码不一致 → 红字 `Passwords do not match`
6. 重复注册 `tester1` → 错误框显示 `username is already taken`（后端 409 文案原样透传）
7. 下拉 → Sign out → 导航栏回到 Login/Register
8. `http://localhost:8080/login` → 用 `admin@mytube.local` / `Admin@123` 登录
   - 期望：导航栏显示 `admin ▾` + `admin` 角色标签，下拉中出现 **Admin panel**，且有 Upload 按钮
9. 登录页故意输错密码 → 错误框显示 `invalid email or password`
10. 未登录访问 `/upload` → 跳登录页；登录后**自动跳回 `/upload`**（redirect 生效）

---

## Task 11: MyVideosView + AdminUsersView

**Files:**
- Modify: `youtube-system/frontend/src/views/MyVideosView.vue`（覆盖占位）
- Modify: `youtube-system/frontend/src/views/AdminUsersView.vue`（覆盖占位）

- [ ] **Step 1: 写 MyVideosView.vue**

```vue
<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { extractError, listMyVideos, retryVideo } from '../api'

const router = useRouter()
const videos = ref([])
const error = ref('')
const busyId = ref('')
let timer = null

function fmtDuration(sec) {
  if (!sec) return ''
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function fmtDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : ''
}

async function refresh() {
  try {
    const { data } = await listMyVideos()
    videos.value = data.videos
  } catch (e) {
    error.value = extractError(e, 'Could not load your videos')
  }
}

async function doRetry(id) {
  busyId.value = id
  error.value = ''
  try {
    await retryVideo(id)
    await refresh()
  } catch (e) {
    error.value = extractError(e, 'Retry failed')
  } finally {
    busyId.value = ''
  }
}

onMounted(() => {
  refresh()
  // Poll only while something is still in flight; the backend drives statuses.
  timer = setInterval(() => {
    if (videos.value.some((v) => v.status === 'pending' || v.status === 'processing')) {
      refresh()
    }
  }, 4000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2 style="margin-top: 0">My videos</h2>
    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="videos.length === 0" class="empty-state">
      <p>You have not uploaded anything yet.</p>
      <RouterLink to="/upload" class="btn">Upload your first video</RouterLink>
    </div>

    <div class="grid">
      <div v-for="v in videos" :key="v.id" class="card" @click="router.push(`/watch/${v.id}`)">
        <img v-if="v.thumbnail_url" class="thumb" :src="v.thumbnail_url" alt="" />
        <div v-else class="thumb-placeholder">🎬</div>
        <div class="card-body">
          <p class="card-title">{{ v.title }}</p>
          <div class="card-meta">
            <span class="badge" :class="v.status">{{ v.status }}</span>
            <span v-if="v.duration_sec"> · {{ fmtDuration(v.duration_sec) }}</span>
          </div>
          <p class="uploader">{{ fmtDate(v.created_at) }}</p>
          <button
            v-if="v.status === 'failed'"
            class="btn tiny"
            style="margin-top: 8px"
            :disabled="busyId === v.id"
            @click.stop="doRetry(v.id)"
          >
            {{ busyId === v.id ? 'Retrying…' : 'Retry transcode' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 写 AdminUsersView.vue**

```vue
<script setup>
import { computed, onMounted, ref } from 'vue'
import { banUser, extractError, listUsers, setUserRole, unbanUser } from '../api'
import { authState } from '../auth'

const PAGE_SIZE = 50
const ROLES = ['user', 'creator', 'moderator', 'admin']

const users = ref([])
const total = ref(0)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const busyId = ref('')

const canLoadMore = computed(() => users.value.length < total.value)
const myId = computed(() => authState.user?.id)

function fmtDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString() : ''
}

async function load(reset = false) {
  loading.value = true
  error.value = ''
  try {
    const offset = reset ? 0 : users.value.length
    const { data } = await listUsers(PAGE_SIZE, offset)
    total.value = data.total
    users.value = reset ? data.users : users.value.concat(data.users)
  } catch (e) {
    error.value = extractError(e, 'Could not load users')
  } finally {
    loading.value = false
  }
}

async function changeRole(user, role) {
  busyId.value = user.id
  error.value = ''
  notice.value = ''
  try {
    const { data } = await setUserRole(user.id, role)
    user.role = data.role
    // The new role lands in that user's NEXT access token, not the current one.
    notice.value = `${user.username} is now ${role}. They must sign in again for it to take effect.`
  } catch (e) {
    error.value = extractError(e, 'Could not change role')
    await load(true)   // roll the select back to server truth
  } finally {
    busyId.value = ''
  }
}

async function toggleBan(user) {
  busyId.value = user.id
  error.value = ''
  notice.value = ''
  try {
    const banning = user.status === 'active'
    const { data } = banning
      ? await banUser(user.id, 'banned by admin')
      : await unbanUser(user.id)
    user.status = data.status
    notice.value = banning
      ? `${user.username} was banned; their sessions were revoked.`
      : `${user.username} was unbanned.`
  } catch (e) {
    error.value = extractError(e, 'Operation failed')
  } finally {
    busyId.value = ''
  }
}

onMounted(() => load(true))
</script>

<template>
  <div>
    <h2 style="margin-top: 0">
      Users <small style="color: var(--text-dim)">({{ total }})</small>
    </h2>

    <div v-if="error" class="error-box">{{ error }}</div>
    <div v-if="notice" class="hint-box">{{ notice }}</div>

    <div class="table-wrap">
      <table class="users">
        <thead>
          <tr>
            <th>Username</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th>Registered</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>
              {{ u.username }}
              <span v-if="u.id === myId" style="color: var(--text-dim)">(you)</span>
            </td>
            <td style="color: var(--text-dim)">{{ u.email }}</td>
            <td>
              <select
                :value="u.role"
                :disabled="u.id === myId || busyId === u.id"
                @change="changeRole(u, $event.target.value)"
              >
                <option v-for="r in ROLES" :key="r" :value="r">{{ r }}</option>
              </select>
            </td>
            <td>
              <span class="badge" :class="u.status === 'banned' ? 'failed' : 'ready'">
                {{ u.status }}
              </span>
            </td>
            <td style="color: var(--text-dim)">{{ fmtDate(u.created_at) }}</td>
            <td>
              <div class="row-actions">
                <button
                  class="btn tiny"
                  :class="{ danger: u.status === 'active' }"
                  :disabled="u.id === myId || busyId === u.id"
                  @click="toggleBan(u)"
                >
                  {{ u.status === 'active' ? 'Ban' : 'Unban' }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="!users.length && !loading" class="empty-state">No users found.</p>

    <button
      v-if="canLoadMore"
      class="btn secondary"
      style="margin-top: 16px"
      :disabled="loading"
      @click="load()"
    >
      {{ loading ? 'Loading…' : `Load more (${users.length}/${total})` }}
    </button>
  </div>
</template>
```

自己那一行的所有控件都 `disabled`，对应后端 `cannot change your own role` / `cannot ban yourself` 的 400。

- [ ] **Step 3: 构建部署**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose build frontend; docker compose up -d frontend
```

- [ ] **Step 4: 浏览器验证**

1. admin 登录 → 下拉 → **Admin panel** → `/admin/users`
   - 期望：表格列出所有用户（含 Task 7 e2e 留下的测试用户），显示用户名 / 邮箱 / 角色下拉 / 状态徽章 / 注册日期
   - 期望：admin 自己那行标 `(you)`，角色下拉与 Ban 按钮均为禁用态
2. 把 `tester1` 的角色从 `user` 改为 `creator`
   - 期望：蓝色提示框 `tester1 is now creator. They must sign in again for it to take effect.`
3. Ban `tester1` → 状态徽章变红 `banned`，提示 `... sessions were revoked.`
4. Unban `tester1` → 徽章变绿 `active`
5. 被 ban 期间用 `tester1` 登录 → 错误框 `account is banned`；unban 后可正常登录
6. 以非 admin 身份手动访问 `http://localhost:8080/admin/users` → **被弹回首页**（守卫生效，不暴露该页存在）
7. tester1（已提升为 creator 且**重新登录**）→ 导航栏出现 Upload 按钮 → 下拉 → **My videos**
   - 期望：空状态显示 `You have not uploaded anything yet.` + 上传按钮
8. 上传一个视频后回到 My videos → 卡片出现，状态从 pending → processing → ready 自动刷新（4s 轮询）

---

## Task 12: 改造 HomeView / UploadView / WatchView

**Files:**
- Modify: `youtube-system/frontend/src/views/HomeView.vue`（现 56 行）
- Modify: `youtube-system/frontend/src/views/UploadView.vue`（现 104 行）
- Modify: `youtube-system/frontend/src/views/WatchView.vue`（现 133 行）

- [ ] **Step 1: HomeView 卡片显示上传者**

`<script setup>` 中，在 `function fmtDuration(sec) {` 之前插入：

```js
function uploaderName(v) {
  return v.uploader?.username || 'Anonymous'
}
```

模板中，将 `.card-body` 内的这一段：

```html
          <div class="card-meta">
            <span class="badge" :class="v.status">{{ v.status }}</span>
            <span v-if="v.duration_sec"> · {{ fmtDuration(v.duration_sec) }}</span>
          </div>
```

替换为：

```html
          <p class="uploader">{{ uploaderName(v) }}</p>
          <div class="card-meta">
            <span class="badge" :class="v.status">{{ v.status }}</span>
            <span v-if="v.duration_sec"> · {{ fmtDuration(v.duration_sec) }}</span>
          </div>
```

再把空状态文案（对无上传权限的访客是误导）：

```html
      <p>No videos yet. Click Upload to add your first one.</p>
```

改为：

```html
      <p>No videos yet.</p>
```

- [ ] **Step 2: UploadView 处理角色不足**

`<script setup>` 中，将开头三行 import：

```js
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { getUploadUrl, uploadBinary, createVideo } from '../api'
```

替换为：

```js
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createVideo, extractError, getUploadUrl, uploadBinary } from '../api'
import { authState, hasRole } from '../auth'
```

在 `const dragging = ref(false)` 之后插入：

```js
// A signed-in 'user' passes the route guard but still lacks upload rights;
// explain it inline instead of letting a raw backend 403 surface.
const canUpload = computed(() => hasRole('creator'))
```

在 `submit()` 开头插入权限前置检查，即把：

```js
async function submit() {
  error.value = ''
  if (!file.value) { error.value = 'Please choose a video file'; return }
```

改为：

```js
async function submit() {
  error.value = ''
  if (!canUpload.value) {
    error.value = 'Uploading requires the creator role'
    return
  }
  if (!file.value) { error.value = 'Please choose a video file'; return }
```

把 catch 块：

```js
  } catch (e) {
    error.value = e?.response?.data?.detail || e.message || 'Upload failed'
  } finally {
```

替换为：

```js
  } catch (e) {
    error.value = e?.response?.status === 403
      ? 'Uploading requires the creator role. Ask an admin to promote your account.'
      : extractError(e, 'Upload failed')
  } finally {
```

模板中，在 `<h2>Upload a video</h2>` 之后插入：

```html
    <div v-if="!canUpload" class="hint-box">
      Your account has the <strong>{{ authState.user?.role }}</strong> role.
      Uploading requires <strong>creator</strong> or above — ask an admin to
      promote you, then sign in again.
    </div>
```

并把提交按钮：

```html
    <button class="btn" :disabled="uploading" @click="submit">
```

改为：

```html
    <button class="btn" :disabled="uploading || !canUpload" @click="submit">
```

- [ ] **Step 3: WatchView 显示上传者 + retry 权限化**

`<script setup>` 中，将开头四行 import：

```js
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import Hls from 'hls.js'
import { getVideo, retryVideo } from '../api'
```

替换为：

```js
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import Hls from 'hls.js'
import { extractError, getVideo, retryVideo } from '../api'
import { authState, hasRole } from '../auth'
```

在 `let timer = null` 之后插入：

```js
const uploaderName = computed(() => video.value?.uploader?.username || 'Anonymous')

// Owner or staff (moderator+) may retry - mirrors the backend rule exactly.
const canRetry = computed(() => {
  const me = authState.user
  if (!me || !video.value) return false
  return video.value.uploader?.id === me.id || hasRole('moderator')
})
```

将 `load()` 的 catch 与 `doRetry()` 的 catch 中两处：

```js
    error.value = e?.response?.data?.detail || e.message
```

都替换为：

```js
    error.value = extractError(e)
```

模板中，将：

```html
        <h2 style="margin: 14px 0 4px">{{ video.title }}</h2>
        <p style="color: var(--text-dim)">{{ video.description }}</p>
```

替换为：

```html
        <h2 style="margin: 14px 0 4px">{{ video.title }}</h2>
        <p class="uploader">👤 {{ uploaderName }}</p>
        <p style="color: var(--text-dim)">{{ video.description }}</p>
```

将失败分支里的 retry 按钮：

```html
          <button class="btn" style="margin-left: 12px" @click="doRetry">Retry</button>
```

替换为：

```html
          <button v-if="canRetry" class="btn" style="margin-left: 12px" @click="doRetry">
            Retry
          </button>
```

`canRetry` 依赖 `video.value.uploader.id`，而 `GET /api/videos/{id}` 的 `_card()` 已在 Task 6 Step 3 输出该字段。

- [ ] **Step 4: 构建部署**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose build frontend; docker compose up -d frontend
```

- [ ] **Step 5: 浏览器验证**

1. **匿名**打开首页 → 视频卡片显示上传者用户名；Task 7 遗留的 `Legacy anonymous` 视频显示 `Anonymous`
2. **匿名**打开某个 ready 视频 → 标题下方显示 `👤 <用户名>`；播放正常、画质切换正常
3. 用 creator 种子账号（`creator@mytube.local` / `Creator@123`）登录 → 上传一个新视频 → 完成后首页该卡片显示 `creator`
4. 打开一个 **failed** 视频（Task 7 的 `Corrupt` 视频）：
   - 上传者本人登录 → 显示 Retry 按钮
   - 匿名或他人（非 moderator）→ **不显示** Retry 按钮，仅显示错误文案
   - moderator/admin 登录 → 显示 Retry 按钮
5. 用 `user` 角色账号访问 `/upload` → 顶部蓝色提示框说明需 creator 角色，Upload 按钮禁用
6. admin 把该 user 提升为 creator → **不重新登录**直接刷新 `/upload` → 提示框仍在（旧 JWT 里的 role 未变，符合规格 §4.1）→ 登出重新登录后提示框消失、可正常上传

---

## Task 13: 全栈验证 + README 更新

**Files:**
- Modify: `youtube-system/README.md`

- [ ] **Step 1: 全栈重建并确认 5 个容器健康**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose up -d --build; docker compose ps
```

后台执行 + `GetTerminalOutput` 轮询。

Expected: `redis` / `api-server` / `transcoder-worker` / `cdn` / `frontend` 全部 `Up`（redis 显示 `healthy`）。

- [ ] **Step 2: 跑通规格 §8.2 人工验证清单**

| # | 验证项 | 期望 |
|---|--------|------|
| 1 | 注册新用户 | 成功后自动登录并跳首页；导航栏显示用户名与下拉菜单 |
| 2 | 登录态访问 `/upload` | 正常显示上传表单 |
| 3 | 登出后访问 `/upload` | 重定向到 `/login?redirect=/upload`；登录后自动跳回 `/upload` |
| 4 | admin 打开 `/admin/users` | 可改角色、可封禁/解封 |
| 5 | 普通账号访问 `/admin/users` | 被弹回首页 |
| 6 | 改角色后 | 行内提示「该用户需重新登录后生效」 |
| 7 | user 角色 | 导航栏无 Upload 按钮；直接访问 `/upload` 显示角色不足提示 |
| 8 | 视频卡片与观看页 | 显示上传者用户名；历史视频显示 Anonymous |
| 9 | 观看页 retry 按钮 | 本人可见、他人不可见、moderator 可见 |
| 10 | 自动续期 | 见 Step 3 |

- [ ] **Step 3: 验证 access token 过期后的无感续期**

临时把 TTL 调到 30 秒：

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; (Get-Content docker-compose.yml) -replace 'ACCESS_TOKEN_TTL: "900"', 'ACCESS_TOKEN_TTL: "30"' | Set-Content docker-compose.yml; docker compose up -d api-server
```

浏览器操作：登录 → 打开首页 → **等待 40 秒以上** → 点击导航栏下拉菜单或触发一次列表刷新。

Expected: 页面**不跳转登录页**，请求照常成功（拦截器静默完成了刷新）。在 DevTools → Application → Local Storage 可观察到 `mytube_access` 的值已变化，`mytube_refresh` 也随之更新（轮换）。

**验证完必须改回 900**：

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; (Get-Content docker-compose.yml) -replace 'ACCESS_TOKEN_TTL: "30"', 'ACCESS_TOKEN_TTL: "900"' | Set-Content docker-compose.yml; docker compose up -d api-server; Select-String -Path docker-compose.yml -Pattern 'ACCESS_TOKEN_TTL'
```

Expected: 输出含 `ACCESS_TOKEN_TTL: "900"`

- [ ] **Step 4: 更新 README.md**

**4a.** 在「功能特性」列表末尾追加：

```markdown
- **用户系统与四级角色**：注册/登录，`user < creator < moderator < admin` 单向包含的权限层级
- **双层令牌认证**：JWT access token（15min，本地验签 + 一次 Redis 封禁标记检查）+ 不透明 refresh token（Redis，7d，每次刷新轮换）
- **重放防护**：提交已轮换掉的 refresh token 会吊销该用户全部会话并强制重新登录
- **视频归属与管理后台**：视频记录上传者，`/my-videos` 管理自己的上传，`/admin/users` 改角色与封禁
```

**4b.** 在架构章节的容器说明之后，新增一节：

````markdown
### 认证与授权

采用**模块化单体**：认证逻辑位于 `api-server` 内的 `app/auth/` 子包，不新增容器，worker/cdn 完全不参与认证。

```
app/auth/
├── schemas.py       请求/响应模型与字段校验
├── security.py      纯函数层：bcrypt、JWT 编解码、ROLE_LEVEL、refresh 键构造
├── service.py       业务逻辑，唯一触碰 users 表与 Redis refresh 键
├── dependencies.py  CurrentUser / get_current_user / require_role
└── router.py        /api/auth/* 与 /api/users/*，领域异常 → HTTP 状态码
```

依赖方向单向：`router → service → (security, database)`；`dependencies → security`。

**令牌流转**

| 令牌 | 形态 | 客户端存储 | 服务端存储 | TTL | 校验方式 |
|------|------|-----------|-----------|-----|----------|
| access | JWT (HS256) | localStorage | 无 | 15min | 本地验签不查库 + 1 次 Redis EXISTS 查封禁标记 |
| refresh | `{user_id}.{随机串}` | localStorage | Redis 仅存 SHA-256 | 7d | 查 Redis + 查 users 表确认未封禁 |

refresh token 每次使用即**轮换**（删旧键、写新键）。若提交的令牌在 Redis 中已不存在，视为重放攻击，吊销该用户全部会话并要求重新登录——这也是令牌必须内嵌 `user_id` 的原因：键不存在时无从反查归属。

**封禁即时生效**：`ban` 操作除吊销全部 refresh 外，还置一个用户级 Redis 标记 `auth:ban:{user_id}`（TTL=`BAN_MARKER_TTL`，默认 1d）；`get_current_user` 本地验签后做一次 O(1) `EXISTS` 命中即 403，因此**封禁对正在使用的 access token 也立即生效**（`unban` 删除该标记）。**角色变更**因签在 access payload 内，仍需重登/刷新才生效（≤15min）。

**前端零循环依赖**：`tokens.js`（零依赖）← `api.js` ← `auth.js` ← `router.js`/视图；会话失效后的跳转由 `main.js` 注入回调，避免 `api.js` 反向依赖 router。
````

**4c.** 在 API 章节的端点表之后追加两张表：

```markdown
### 认证

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/auth/register` | 公开 | 注册，返回 `{user}`（不含令牌） |
| POST | `/api/auth/login` | 公开 | 登录，返回 access + refresh |
| POST | `/api/auth/refresh` | 公开 | 轮换 refresh token |
| POST | `/api/auth/logout` | 登录 | 吊销全部 refresh token，204 |
| GET | `/api/auth/me` | 登录 | 当前用户信息 |

### 用户管理

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/users` | admin | 用户列表，`?limit=50&offset=0`（limit ≤ 100） |
| GET | `/api/users/{id}` | 公开 | 公开投影 `{id, username, role}` |
| PATCH | `/api/users/{id}/role` | admin | 改角色（不能改自己） |
| POST | `/api/users/{id}/ban` | admin | 封禁并吊销会话（不能封自己） |
| POST | `/api/users/{id}/unban` | admin | 解封 |
| GET | `/api/videos/mine` | creator+ | 我的上传（含 failed） |

权限变化：`POST /api/upload-url` 与 `POST /api/videos` 现需 **creator+**；`POST /api/videos/{id}/retry` 需登录且为本人或 **moderator+**；`GET /api/stats` 收紧为 **moderator+**。`POST /api/upload/{token}` 仍不带 JWT——预签名 token 本身即凭证，归属校验推迟到 `POST /api/videos`。
```

**4d.** 在快速开始章节追加种子账号表（**必须带安全警示**）：

```markdown
### 种子账号

首次启动时自动创建，便于本地体验：

| 用户名 | 邮箱 | 密码 | 角色 |
|--------|------|------|------|
| admin | `admin@mytube.local` | `Admin@123` | admin |
| creator | `creator@mytube.local` | `Creator@123` | creator |

> ⚠️ **仅用于本地测试**。这两个是硬编码弱口令账号，`JWT_SECRET` 也是默认开发值。
> 部署到任何可被外部访问的环境前，必须修改 `docker-compose.yml` 中的 `JWT_SECRET`，
> 并删除 `app/auth/service.py` 里的 `SEED_USERS`。
```

**4e.** 在设计要点章节追加：

```markdown
- **单写者原则不变**：users 表与 videos/renditions 同在一个 SQLite，仍只有 api-server 写入
- **历史数据兼容**：`videos.uploader_id` 可空，用户系统上线前的视频显示为 Anonymous 且照常播放；迁移用 `PRAGMA table_info` 探测后再 `ALTER TABLE`，可重复执行
- **预签名归属校验**：`presign.claim_owner()` 一次性消费 `video_id → user_id` 映射，防止冒名注册他人上传的视频
- **角色层级前后端各一份**：后端 `app/auth/security.py` 的 `ROLE_LEVEL` 与前端 `src/auth.js` 的 `ROLE_LEVEL` 必须保持一致
```

- [ ] **Step 5: 最终确认**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; docker compose ps; Write-Output "---"; Invoke-RestMethod http://localhost:8000/api/health; Write-Output "---"; Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login -ContentType 'application/json' -Body '{"email":"admin@mytube.local","password":"Admin@123"}' | Select-Object token_type, expires_in
```

Expected: 5 个容器 Up；`status : ok`；`token_type : bearer`、`expires_in : 900`。

- [ ] **Step 6: 确认无临时文件残留**

Run:

```powershell
Set-Location D:\StudyProjects\system-design-notes\youtube-system; Get-ChildItem -Recurse -Include "_verify_*.py","test_auth_e2e.py","test_video.mp4","test_corrupt.mp4" | Select-Object FullName; Get-ChildItem data -Filter "_verify*.db" -ErrorAction SilentlyContinue | Select-Object FullName
```

Expected: 无输出（所有临时验证产物已清理）。

---

## 完成标准

- [ ] 规格 §1–§7 全部实现；§9「明确不做」清单中的项**未被实现**
- [ ] 规格 §8.1 的 12 项 e2e 断言组全部通过（Task 7 Step 5）
- [ ] 规格 §8.2 的 8 项人工清单全部通过（Task 13 Step 2–3）
- [ ] 上一轮的视频上传→转码→播放功能未被破坏（Task 12 Step 5 第 1–3 项）
- [ ] 所有临时验证脚本与测试媒体文件已删除（Task 13 Step 6）
- [ ] README 含种子账号与 `JWT_SECRET` 的安全警示
- [ ] `docker-compose.yml` 的 `ACCESS_TOKEN_TTL` 已还原为 `"900"`
