# MyTube 用户系统与登录 设计规格

**日期**：2026-09-17
**范围**：为已实现的 `youtube-system`（视频上传→转码→HLS 播放）新增用户系统与登录认证。
**方案**：模块化单体——在现有 `api-server` 内新增 `app/auth/` 子包，不新增容器。

## 背景与范围界定

用户提出四项新功能：DRM/水印加密、用户系统/登录、评论点赞、视频内容审核。四者存在明确依赖关系，用户系统是其余三项的地基：

```
用户系统/登录  ←── 本轮
    ├── 评论点赞      （需要评论者身份）
    ├── 视频内容审核  （需要上传者身份 + moderator 角色）
    └── DRM/水印加密  （需要播放授权体系）
```

经确认拆为 4 轮，每轮独立走「设计→计划→实现→验证」。本文档仅覆盖第一轮。

**当前系统状态**：`youtube-system` 有 7 个 API 端点、DB 仅 `videos` + `renditions` 两表、前端 3 个视图（Home/Upload/Watch），完全无用户概念，视频无上传者身份。

## 1. 数据模型

### 1.1 新增 users 表

```sql
CREATE TABLE users (
    id            TEXT PRIMARY KEY,               -- secrets.token_hex(12)
    username      TEXT NOT NULL UNIQUE,           -- 3-32 字符，^[a-zA-Z0-9_]+$
    email         TEXT NOT NULL UNIQUE,           -- 转小写后存储
    password_hash TEXT NOT NULL,                  -- bcrypt（含盐）
    role          TEXT NOT NULL DEFAULT 'user',   -- user|creator|moderator|admin
    status        TEXT NOT NULL DEFAULT 'active', -- active|banned
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
```

建表语句加入 `app/database.py` 的 `init_db()`，与 `videos`/`renditions` 同一 `executescript`。api-server 仍是 SQLite 唯一写者。

### 1.2 videos 表变更

新增列 `uploader_id TEXT REFERENCES users(id)`，**可空**。

- 历史数据保持 `NULL`，API 返回 `uploader: null`，前端显示「匿名」
- 新上传强制写入当前用户 id
- 迁移方式：`init_db()` 中执行 `ALTER TABLE videos ADD COLUMN uploader_id TEXT REFERENCES users(id)`，先用 `PRAGMA table_info(videos)` 检测列是否已存在以保证幂等（SQLite 不支持 `ADD COLUMN IF NOT EXISTS`）

### 1.3 角色层级

```
admin(4) > moderator(3) > creator(2) > user(1)
```

权限单向包含：`require_role("moderator")` 放行 moderator 与 admin。等级映射在前后端各维护一份同名常量（后端 `app/auth/security.py` 的 `ROLE_LEVEL`，前端 `src/auth.js` 的 `ROLE_LEVEL`）。

### 1.4 种子账号

`init_db()` 中幂等创建（`INSERT OR IGNORE`，密码经 bcrypt 哈希）：

| 用户名 | 邮箱 | 密码 | 角色 |
|--------|------|------|------|
| admin | admin@mytube.local | Admin@123 | admin |
| creator | creator@mytube.local | Creator@123 | creator |

固定弱密码仅用于本地测试，README 中明确标注不可用于生产。

### 1.5 database.py 新增函数

```python
async def insert_user(user_id, username, email, password_hash, role) -> None
async def get_user_by_email(email) -> dict | None
async def get_user_by_username(username) -> dict | None
async def get_user_by_id(user_id) -> dict | None
async def list_users(limit, offset) -> list[dict]
async def count_users() -> int
async def set_user_role(user_id, role) -> None
async def set_user_status(user_id, status) -> None
async def list_videos_by_uploader(uploader_id) -> list[dict]
```

`list_videos()` 与 `get_video()` 改为 `LEFT JOIN users u ON v.uploader_id = u.id`，返回中附 `uploader_id` 与 `uploader_username`。所有 SQL 仍集中在 `database.py`。

## 2. 认证机制

### 2.1 Access token（JWT，HS256）

```json
{
  "sub": "a1b2c3d4e5f6a7b8c9d0e1f2",
  "username": "alice",
  "role": "creator",
  "type": "access",
  "iat": 1788999100,
  "exp": 1789000000
}
```

签名密钥与 TTL 来自环境变量，`app/config.py` 新增字段（TTL 单位为秒）：

| 字段 | 环境变量 | 默认值 |
|------|----------|--------|
| `jwt_secret` | `JWT_SECRET` | `"dev-only-secret-change-in-production"` |
| `access_token_ttl` | `ACCESS_TOKEN_TTL` | `900`（15min） |
| `refresh_token_ttl` | `REFRESH_TOKEN_TTL` | `604800`（7d） |
| `ban_marker_ttl` | `BAN_MARKER_TTL` | `86400`（1d，封禁标记存活，见 2.5） |

验签纯本地完成（**不查数据库**）；`get_current_user` 仅额外做一次 **Redis GET 检查封禁标记** `auth:ban:{user_id}`（见 2.5）。这样既保留「无 DB 查询、api-server 可水平扩展」的收益，又让封禁即时生效。

代价：**角色变更**（新 role 签在新 access 里）在旧 access 剩余有效期内（≤15min）不生效，需重新登录/刷新拿到新 role。封禁则通过 Redis 标记即时生效（见 2.5）。

### 2.2 Refresh token（不透明随机串，Redis）

```
令牌：  {user_id}.{secrets.token_urlsafe(48)}      -- 例：a1b2c3…f2.kJ83n…
键：    refresh:{user_id}:{sha256(完整令牌)}
值：    {"issued_at": <unix>}
TTL：   config.refresh_token_ttl（默认 604800）
```

服务端只存令牌的 SHA-256（Redis 泄露不等于令牌泄露）。

**为何令牌内嵌 `user_id`**：§2.3 的重放防护要求在「键不存在」时按 user_id 全量吊销，而键不存在就意味着无法从 Redis 反查归属；客户端提交的又只有令牌本身。因此 user_id 必须能从令牌直接解析出来（取 `.` 前缀），否则该防护无法实现。前缀仅暴露用户 id（已随视频元数据公开），不构成额外信息泄露；随机部分仍为 48 字节 `token_urlsafe`，不可猜测。

### 2.3 刷新轮换与重放防护

`POST /api/auth/refresh` 校验通过后**删除旧键并签发新 refresh token**。

若提交的 refresh token 在 Redis 中不存在（说明已被轮换掉，疑似重放），则从令牌前缀解析出 user_id，**SCAN 删除该用户全部 `refresh:{user_id}:*` 键**，返回 401，强制重新登录。令牌格式非法（无 `.` 分隔）直接 401，不做吊销。

### 2.4 登出

`auth:ban:{user_id}` 是**用户级封禁标记**（见 2.5），与登出无关。**登出仅吊销 refresh**：SCAN 删除该用户全部 refresh 键，返回 204。登出者自己设备上的 access token 不主动失效（前端随即清除本地令牌），靠 `access_token_ttl`（默认 15min）自然过期。

### 2.5 封禁即时生效（Redis 封禁标记）

因 access token 本地验签、角色与 id 均签在令牌内，若不做额外处理，封禁只能等 access 过期（≤15min）才生效。为满足「封禁/登出即时吊销」的诉求，引入**用户级封禁标记**：

- `ban` 操作：置 `auth:ban:{user_id} = 1`（TTL 取 `max(access_token_ttl, 剩余风险窗口)`，默认 `86400`/1 天，由 `BAN_MARKER_TTL` 配置）+ SCAN 删除该用户全部 `refresh:*` 键。
- `get_current_user`：本地验签通过后，做一次 `EXISTS auth:ban:{user_id}`；命中则 403 "account is banned"。这是**单次 Redis O(1) GET**，不查数据库，水平扩展不受影响。
- `unban`：删除 `auth:ban:{user_id}`，用户凭有效 refresh 即可恢复（access 过期后重新登录）。
- 登录：检查 `users.status`，`banned` → 403。

综合效果：**封禁对正在使用中的 access 也立即生效**（下一次请求即被 Redis 标记拦截）。`get_current_user` **不查 users 表**（避免每请求 DB 读），角色变更仍需重登生效（见 2.1）。

### 2.6 新增依赖

```
PyJWT==2.9.0
bcrypt==4.2.0
```

不引入 passlib（已停止维护，对 bcrypt 4.x 有兼容告警）。

## 3. 模块结构

```
app/auth/
├── __init__.py
├── schemas.py        # RegisterRequest/LoginRequest/RefreshRequest/TokenPair/UserOut
├── security.py       # bcrypt 哈希与校验、JWT 编解码、ROLE_LEVEL（纯函数，无 IO）
├── service.py        # 注册/登录/刷新/登出/用户管理业务逻辑（唯一触碰 users 表与 refresh 键）
├── dependencies.py   # CurrentUser、get_current_user、get_optional_user、require_role
└── router.py         # /api/auth/* 与 /api/users/* 端点，领域异常 → HTTP 码
```

依赖方向单向：`router → service → (security, database)`；`dependencies → security`。`app/server.py` 仅 `app.include_router(auth_router)` 并给现有端点加依赖，不含认证细节。

`service.py` 抛领域异常（`AuthError` / `PermissionError` / `ConflictError` / `NotFoundError`），`router.py` 统一转 HTTP 状态码，业务层不感知 HTTP。

## 4. API 端点

### 4.1 鉴权依赖

```python
@dataclass
class CurrentUser:
    id: str          # 来自 JWT sub
    username: str    # 来自 JWT username
    role: str        # 来自 JWT role

async def get_current_user(creds = Depends(HTTPBearer(auto_error=False))) -> CurrentUser
    # 缺失/无效/过期/签名错误 → 401；payload type != "access" → 401
    # 本地验签后做一次 Redis GET 检查 auth:ban:{user_id}（见 2.5），命中则 403；不查数据库

async def get_optional_user(creds = Depends(HTTPBearer(auto_error=False))) -> CurrentUser | None
    # 公开端点用：有 token 就解析，无 token 或无效均返回 None，不报错

def require_role(min_role: str) -> Callable
    # 返回依赖：ROLE_LEVEL[user.role] < ROLE_LEVEL[min_role] → 403
    # 文案 "requires {min_role} role or above"
```

`CurrentUser` 全部字段来自 JWT payload，因此**角色变更（如 admin 提升某用户为 creator）同样在 access 剩余有效期内不生效**，受影响用户需重新登录才能拿到含新 role 的 token。

采用 FastAPI 原生 `HTTPBearer`，Swagger UI 自动出现 Authorize 按钮，便于调试。

### 4.2 新增端点

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/auth/register` | 公开 | `{username,email,password}` → 201 `{user}`（**不返回令牌**，前端随后自动调 login） |
| POST | `/api/auth/login` | 公开 | `{email,password}` → `{access_token,refresh_token,token_type:"bearer",expires_in,user}` |
| POST | `/api/auth/refresh` | 公开 | `{refresh_token}` → 新令牌对（轮换；重放则全量吊销；查库确认未封禁） |
| POST | `/api/auth/logout` | 登录 | 吊销全部 refresh → 204 |
| GET | `/api/auth/me` | 登录 | 当前用户 `{id,username,email,role,status,created_at}` |
| GET | `/api/users/{id}` | 公开 | `{id,username,role}` |
| GET | `/api/users` | admin | `{users:[UserOut], total:int}`，`?limit=50&offset=0`（limit 上限 100） |
| PATCH | `/api/users/{id}/role` | admin | `{role}`；不能改自己 → 400；role 非四值之一 → 400 |
| POST | `/api/users/{id}/ban` | admin | `{reason?}` → `status=banned` + 吊销 refresh；不能封自己 → 400 |
| POST | `/api/users/{id}/unban` | admin | 恢复 `status=active` |
| GET | `/api/videos/mine` | creator+ | `{videos:[card]}`，card 结构与 `GET /api/videos` 一致，含 failed |

`/api/videos/mine` 用独立路径而非 `?mine=true`，避免被 `GET /api/videos/{video_id}` 的路径参数吞掉；**路由注册顺序须将 `/mine` 置于 `/{video_id}` 之前**。

`expires_in` 取自 `config.access_token_ttl`，不硬编码。

### 4.3 现有端点改造

| 端点 | 改造 |
|------|------|
| `GET /api/health` | 不变（公开，容器健康检查依赖） |
| `POST /api/upload-url` | 加 `require_role("creator")`；`presign.issue()` 传入 `current_user.id` 记录归属 |
| `POST /api/upload/{token}` | **不加 JWT，也不校验用户身份**（无 JWT 无从校验）。预签名 token 本身即凭证，持有即可上传——与 S3 预签名 URL 语义一致。归属校验推迟到 `POST /api/videos` |
| `POST /api/videos` | 加 `require_role("creator")`；写入 `uploader_id = current_user.id`；**校验 video_id 的预签名归属等于当前用户**，不等则 403（防冒名注册他人上传的视频） |
| `GET /api/videos` | 保持公开；`_card` 增加 `uploader: {id,username} \| null` |
| `GET /api/videos/{id}` | 保持公开；同上增加 `uploader` |
| `POST /api/videos/{id}/retry` | 需登录，且 `uploader_id == current_user.id` 或 moderator+ → 否则 403 |
| `GET /api/stats` | 收紧为 `require_role("moderator")`（运维数据；前端首页未使用，不影响现有功能） |

**presign 归属校验机制**：`consume(token)` 会删除 token 记录，而 `POST /api/videos` 只携带 `video_id`（不带 token），因此需要独立的归属映射：

```python
# app/presign.py 模块级
_owners: dict[str, str] = {}     # video_id -> user_id

def issue(filename, size, user_id) -> dict
    # 生成 video_id/token；_tokens[token] = {video_id, user_id, expires_at}

def consume(token) -> dict | None
    # 弹出 token 记录；同时写入 _owners[video_id] = user_id（供后续归属校验）

def claim_owner(video_id, user_id) -> bool
    # 校验并消费归属：_owners.get(video_id) == user_id 则删除该条并返回 True
```

`_owners` 与 `_tokens` 同为内存字典（单实例设计），`claim_owner` 一次性消费避免残留。

### 4.4 校验规则与错误码

注册校验（Pydantic）：`username` 3–32 字符且匹配 `^[a-zA-Z0-9_]+$`；`email` 标准格式并转小写；`password` ≥ 8 字符（最小可用，不强制复杂度）。

| 码 | 场景 |
|----|------|
| 400 | 密码过弱、角色值非法、封禁/改自己 |
| 401 | 缺失/无效/过期 access、refresh 无效、账号已封禁（刷新时） |
| 403 | 角色等级不足、登录时账号 banned、操作非本人资源、预签名归属不符 |
| 404 | 用户/视频不存在 |
| 409 | username 或 email 已占用 |
| 422 | Pydantic 字段校验失败 |

登录失败统一返回 **401 "invalid email or password"**，不区分邮箱不存在与密码错误，避免账号枚举。

### 4.5 权限矩阵

| 操作 | user | creator | moderator | admin | 匿名 |
|------|:----:|:-------:|:---------:|:-----:|:----:|
| 浏览/观看视频 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 注册/登录 | — | — | — | — | ✅ |
| 上传视频 | ❌ | ✅ | ✅ | ✅ | ❌ |
| 重试自己的失败视频 | ❌ | ✅ | ✅ | ✅ | ❌ |
| 重试他人视频 | ❌ | ❌ | ✅ | ✅ | ❌ |
| 查看 `/api/stats` | ❌ | ❌ | ✅ | ✅ | ❌ |
| 改角色 / 封禁用户 | ❌ | ❌ | ❌ | ✅ | ❌ |

## 5. 前端

### 5.1 文件结构

```
frontend/src/
├── auth.js                 # 【新】令牌存储 + authState + login/register/logout/restore/hasRole
├── api.js                  # 【改】axios 拦截器 + auth 接口 + extractError
├── router.js               # 【改】新增 4 路由 + beforeEach 守卫
├── main.js                 # 【改】await restore() 后再 mount
├── App.vue                 # 【改】导航栏身份态 + 用户下拉菜单
└── views/
    ├── LoginView.vue       # 【新】
    ├── RegisterView.vue    # 【新】
    ├── MyVideosView.vue    # 【新】我的上传（含 failed，可重试）
    ├── AdminUsersView.vue  # 【新】用户表格 + 改角色 + 封禁/解封（仅 admin）
    ├── HomeView.vue        # 【改】卡片显示上传者用户名
    ├── UploadView.vue      # 【改】403 提示「需 creator 角色」
    └── WatchView.vue       # 【改】显示上传者；retry 按钮仅本人或 moderator+ 可见
```

`auth.js` 导出：

```js
export const authState = reactive({ user: null, ready: false })
export function getAccess(): string | null
export function setTokens(access, refresh): void
export function clearTokens(): void
export async function restore(): Promise<void>
export async function login(email, password): Promise<object>
export async function register(username, email, password): Promise<object>
export async function logout(): Promise<void>
export function hasRole(minRole): boolean
```

`register()` 内部先调 `/api/auth/register`，成功后**自动用同一凭据调 `login()`**（注册端点不返回令牌），因此 `RegisterView` 提交成功后用户已处于登录态，直接跳首页。

令牌存 `localStorage`（键 `mytube_access` / `mytube_refresh`）。学习项目不引入 httpOnly Cookie 与 CSRF 防护。不引入 UI 组件库，下拉菜单用 `ref` + CSS 实现。

### 5.2 axios 拦截器

**请求**：有 access 就加 `Authorization: Bearer <token>`。

**响应 401**（且原请求不是 `/api/auth/login|refresh`）：

1. 共享 Promise 保证并发 401 只触发一次刷新（避免轮换互相吊销）
2. 刷新成功 → 写入新令牌对 → 重放原请求一次（`_retried` 标记防死循环）
3. 刷新失败 → 清令牌、`authState.user = null`、跳 `/login?redirect=<原路径>`

### 5.3 路由守卫

| 路径 | meta | 未满足时 |
|------|------|----------|
| `/login`、`/register` | `guestOnly` | 已登录跳 `/` |
| `/upload` | `requiresAuth`, `role:'creator'` | 未登录 → `/login?redirect=/upload`；角色不足 → 页内提示 |
| `/my-videos` | `requiresAuth` | → `/login?redirect=/my-videos` |
| `/admin/users` | `requiresAuth`, `role:'admin'` | → `/`（不暴露存在） |
| `/`、`/watch/:id` | 无 | 公开 |

`main.js` 中 `await restore()` 完成后再 `mount`，避免刷新页面瞬间误判未登录；代价是首屏多一次 `/me` 往返。

### 5.4 导航栏

```
未登录：  ▶ MyTube                              [Login] [Register]
已登录：  ▶ MyTube        [Upload]  alice ▾
                                            └─ My videos
                                               Admin panel   （仅 admin）
                                               Sign out
```

`[Upload]` 按钮仅 `hasRole('creator')` 时显示。

### 5.5 AdminUsersView

用户表格（用户名/邮箱/角色/状态/注册时间），每行提供：角色下拉（四值）+ Ban/Unban 按钮。分页为 `limit=50` + 「加载更多」按钮（offset 递增追加）。改角色成功后行内提示「该用户需重新登录后生效」。自己的行禁用所有操作控件（对应后端 400）。

## 6. 数据流

**受保护请求**

```
浏览器 ──Authorization: Bearer <access>──▶ api-server
                                            │ HTTPBearer 提取
                                            │ jwt.decode（本地验签）→ EXISTS auth:ban:{uid}
                                            ▼
                                      CurrentUser{id, username, role}
                                            │ require_role(min) 等级比较
                                            ▼
                                        业务端点
```

**access 过期自动续期**

```
请求 ──▶ 401 ──▶ 拦截器 ──▶ POST /api/auth/refresh
                              │ Redis 查 refresh:{uid}:{sha256(token)}
                              │ 命中后查 users 表确认 status == 'active'
                              ├─ 通过 → 删旧键 + 写新键（轮换）→ 新令牌对 ──▶ 重放原请求 ✅
                              ├─ 已封禁 → 吊销全部 refresh → 401 "account is banned"
                              └─ 未命中（已轮换 = 疑似重放）
                                    → SCAN 删除该用户全部 refresh 键
                                    → 401 ──▶ 前端清令牌跳登录
```

## 7. 部署变更

`docker-compose.yml` 的 `api-server` 服务新增环境变量：

```yaml
JWT_SECRET: "dev-only-secret-change-in-production"
ACCESS_TOKEN_TTL: "900"
REFRESH_TOKEN_TTL: "604800"
BAN_MARKER_TTL: "86400"
```

`app/config.py` 新增对应字段（见 2.1 表格）。worker 容器无需变更（不参与认证）。CDN 容器无需变更（媒体仍公开可访问，DRM 留待第四轮）。前端 nginx 反代无需变更（`/api/` 已全量代理）。

`requirements.txt` 新增 `PyJWT==2.9.0`、`bcrypt==4.2.0`，需重新构建 api-server 镜像。

## 8. 测试方案

### 8.1 端到端脚本

`youtube-system/test_auth_e2e.py`（验证通过后删除，与上轮 `test_e2e.py` 做法一致），覆盖：

1. 注册新用户 → 201（响应体无令牌字段）；重复用户名 → 409；重复邮箱 → 409
2. 登录 → 拿到令牌对；错误密码 → 401；不存在的邮箱 → 401（**两次 detail 文案完全相同**）
3. `GET /api/auth/me`：带 access → 200；不带 → 401；篡改签名的 token → 401
4. 新注册用户（user 角色）`POST /api/upload-url` → 403；admin 提升其为 creator 后**用旧 access 重试仍 403**（role 已签入旧 token）；**重新登录**后 → 200
5. 完整上传 + 转码 → `GET /api/videos/mine` 含该视频且 `uploader.username` 正确
6. 历史匿名视频（`uploader_id IS NULL`）的 `uploader` 字段为 `null`
7. 用 A 的 video_id 以 B 的身份调 `POST /api/videos` → 403（预签名归属校验生效）
8. `POST /api/auth/refresh` → 新令牌对；用**旧** refresh 再次刷新 → 401，且刚拿到的新令牌也被吊销（重放防护生效）
9. `POST /api/auth/logout` → 204；此后 refresh → 401
10. admin 封禁该用户 → 其登录 403；其 refresh 立即 401；**已持有的 access 调 `/me` 立即返回 403**（get_current_user 命中 Redis 封禁标记，封禁即时生效）；admin 解封后重新登录 → 200
11. 权限矩阵（4.5 表格）逐格验证
12. admin 改自己角色 → 400；admin 封自己 → 400；`PATCH role` 传非法值（如 `"superuser"`）→ 400

### 8.2 前端人工验证清单

- 注册（成功后自动登录并跳首页）→ 导航栏显示用户名与下拉菜单
- 访问 `/upload` 正常；登出后访问被重定向到 `/login?redirect=/upload`，登录后自动跳回 `/upload`
- admin 账号打开 `/admin/users` 改角色、封禁；普通账号访问该路径被弹回首页
- 改角色后行内提示「该用户需重新登录后生效」
- user 角色看不到 Upload 按钮，直接访问 `/upload` 显示角色不足提示
- 视频卡片与观看页显示上传者用户名；历史视频显示「匿名」
- 观看页 retry 按钮：本人可见、他人不可见（moderator 登录时可见）
- 手动缩短 `ACCESS_TOKEN_TTL`（如 30s）验证自动续期无感（页面不跳登录）

### 8.3 文档更新

`youtube-system/README.md` 新增：认证机制说明（双层令牌 + 轮换）、角色权限矩阵、种子账号表（含「仅本地测试」警示）、新增端点表、封禁生效窗口说明。

## 9. 明确不做（YAGNI）

- 邮箱验证、找回密码（本地无真实邮件服务）
- 登录失败限流/账号锁定
- httpOnly Cookie 与 CSRF 防护
- RBAC 权限表（角色→权限动态映射）
- OAuth 第三方登录
- 视频可见性（public/unlisted/private）
- 用户头像上传、个人资料编辑
- 媒体访问鉴权（CDN 仍公开，属第四轮 DRM 范围）
- access token 逐个拉黑（仅用用户级 `auth:ban` 标记实现封禁即时生效；登出场景仍靠短 TTL 自然过期）
