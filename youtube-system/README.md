# MyTube — YouTube 视频流系统

基于《System Design Interview》第 14 章（Youtube 设计）实现的完整视频上传→转码→流媒体播放系统。

## 功能特性

- **并行上传流程**：元数据与视频二进制分离处理，二进制经预签名 URL 直传存储
- **真实 ffmpeg 转码**：按源分辨率自适应产出 1080p / 720p / 480p 三档 HLS
- **HLS 自适应码率播放**：master.m3u8 + GOP 对齐分片，浏览器可切换画质
- **消息队列解耦**：Redis List 队列，上传与转码流水线完全解耦
- **事件驱动状态回写**：Worker 只发事件不写库，api-server 单写者更新 SQLite
- **错误分类与重试**：可恢复错误（退避重试 2/4/8s）与不可恢复错误（直接 failed）区分；failed 视频支持一键重试
- **Worker 心跳与水平扩展**：`worker:{instance_id}` 心跳键 + `/api/stats` 实时统计，`docker compose up --scale transcoder-worker=N` 即可扩容
- **完整前端**：Vue 3 暗色主题，视频网格 / 拖拽上传（进度条）/ HLS 播放器（画质切换）
- **用户系统与四级角色**：注册/登录，`user < creator < moderator < admin` 单向包含的权限层级
- **双层令牌认证**：JWT access token（15min，本地验签 + 一次 Redis 封禁标记检查）+ 不透明 refresh token（Redis，7d，每次刷新轮换）
- **重放防护**：提交已轮换掉的 refresh token 会吊销该用户全部会话并强制重新登录
- **视频归属与管理后台**：视频记录上传者，`/my-videos` 管理自己的上传，`/admin/users` 改角色与封禁
- **评论与 1 级回复**：视频下评论、回复归入同一顶级线程；读公开、登录可写
- **评论赞/踩**：每人每评论一票，可切换/取消，反范式净分用于热度排序
- **评论治理**：作者软删除自己评论（留占位），moderator/admin 可删任意
- **视频内容审核** — 先审后发（moderator+ 审核队列 approve/reject）；拒绝可编辑后重新提交，不重转码
- **视频 DRM**：新视频转码时 AES-128 加密 HLS 分片，密钥经 `/api/keys/{video_id}` 鉴权端点分发（需登录 + 视频已通过审核），前端叠加半透明水印（用户名）用于溯源。存量视频不受影响

## 架构

```
                    ┌─────────────┐
  浏览器 ──上传元数据──▶  api-server │──insert──▶ SQLite (videos/renditions)
  浏览器 ──二进制流───▶  (FastAPI)  │◀──消费─── transcode:events
                    └──────┬──────┘
                           │ push task
                           ▼
                   ┌──────────────┐         ┌─────────────────┐
                   │ Redis 队列    │──BLPOP──▶ transcoder-worker │──▶ ffmpeg
                   │ transcode:tasks│        │ (Preprocessor/  │    多档并行编码
                   └──────────────┘         │  Resource Mgr/  │
                                            │  Task Workers)  │
                                            └───────┬─────────┘
                                                    │ 写 HLS 分片
                                                    ▼
  浏览器 ◀──/media/*.m3u8,*.ts──┌─────┐    ./data/transcoded/{video_id}/
                                │ CDN │        ├── master.m3u8
                                └─────┘        ├── 1080p/playlist.m3u8 + seg_*.ts
                                               ├── 720p/ ...
                                               ├── 480p/ ...
                                               └── thumbnail.jpg
```

转码流水线（Worker 内部，对应设计文档 DAG Scheduler + Resource Manager + Task Workers）：

```
任务 ─▶ Preprocessor(ffprobe 校验/选档) ─▶ processing 事件
     ─▶ Resource Manager(Semaphore 并发) ┬▶ 1080p 编码 ┐
                                          ├▶ 720p  编码 ├▶ master.m3u8 ─▶ ready 事件
     thumbnail.jpg（失败非致命）───────────┘▶ 480p  编码 ┘
```

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

## 目录结构

```
youtube-system/
├── app/                     # api-server（单写者）
│   ├── config.py            # 配置（路径/队列/上传限制）
│   ├── models.py            # Pydantic 请求模型
│   ├── database.py          # aiosqlite 数据访问
│   ├── presign.py           # 预签名 token（单次使用/TTL 300s）
│   ├── queue.py             # Redis 队列助手
│   ├── completion_consumer.py  # 事件消费 → 状态回写
│   ├── drm.py              # DRM 密钥生成 + GET /api/keys/{id}
│   └── server.py            # FastAPI 7+ 端点
├── worker/                  # 转码 Worker（可多实例）
│   ├── config.py
│   ├── preprocessor.py      # ffprobe + 档位选择
│   ├── task_worker.py       # ffmpeg 编码/缩略图/master 播放列表
│   ├── resource_manager.py  # Semaphore 并发控制 + 排空
│   ├── pipeline.py          # 流水线编排 + 事件上报
│   └── main.py              # 心跳/消费循环/health
├── cdn/nginx.conf           # HLS MIME + CORS
├── frontend/                # Vue 3 + HLS.js
├── api.Dockerfile / worker.Dockerfile
└── docker-compose.yml
```

## 快速开始

```powershell
cd youtube-system
docker compose up -d --build
```

启动后访问：

| 服务 | 地址 |
|------|------|
| Web 前端 | http://localhost:8080 |
| api-server | http://localhost:8000/docs |
| CDN（媒体流） | http://localhost:8003 |

使用流程：打开 http://localhost:8080 → Upload → 拖入视频文件填写标题 → 上传后首页卡片显示 `pending → processing` → 转码完成后变 `ready`（约 10s 测试视频需 20~60s）→ 点击卡片观看，可切换画质。

水平扩容 Worker：

```powershell
docker compose up -d --scale transcoder-worker=3
```

### 种子账号

首次启动时自动创建，便于本地体验：

| 用户名 | 邮箱 | 密码 | 角色 |
|--------|------|------|------|
| admin | `admin@mytube.local` | `Admin@123` | admin |
| creator | `creator@mytube.local` | `Creator@123` | creator |

> ⚠️ **仅用于本地测试**。这两个是硬编码弱口令账号，`JWT_SECRET` 也是默认开发值。
> 部署到任何可被外部访问的环境前，必须修改 `docker-compose.yml` 中的 `JWT_SECRET`，
> 并删除 `app/auth/service.py` 里的 `SEED_USERS`。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/upload-url | 预签名上传（body: filename/size/content_type） |
| POST | /api/upload/{token} | 二进制流式上传（?filename= 推导扩展名） |
| POST | /api/videos | 注册元数据并入转码队列 |
| GET | /api/videos | 视频卡片列表 |
| GET | /api/videos/{id} | 详情（ready 含 stream_url 与 renditions） |
| POST | /api/videos/{id}/retry | 失败重试（仅 failed） |
| GET | /api/stats | Worker 数/排队任务数/各状态视频数 |

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

### 评论与点赞

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/videos/{video_id}/comments` | 公开 | 顶级评论分页，`?sort=top\|new&limit&offset`；登录附 `my_vote` |
| GET | `/api/comments/{id}/replies` | 公开 | 该线程回复，时间正序分页 |
| POST | `/api/videos/{video_id}/comments` | 登录 | body `{content, reply_to?}` 建评论/回复 |
| DELETE | `/api/comments/{id}` | 作者或 moderator+ | 软删除，204 |
| PUT | `/api/comments/{id}/vote` | 登录 | body `{value: 1\|-1\|0}`，0 撤票 |

投票计数走 `comments` 冗余列（`like_count/dislike_count/score`）+ `comment_votes(user_id, comment_id, value)` 主键唯一，`apply_vote` 单事务更新。模块位于 `app/comments/`（`schemas/service/router`），复用 `app/auth/dependencies` 的鉴权与 `ROLE_LEVEL`。

### 视频审核（Moderation）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/moderation/queue` | moderator+ | 待审列表 `{videos, total}`，`?limit&offset` |
| POST | `/api/moderation/{id}/approve` | moderator+ | 通过 → 204 |
| POST | `/api/moderation/{id}/reject` | moderator+ | 拒绝 `{reason}` → 204 |
| POST | `/api/videos/{id}/resubmit` | owner | 重新提交 `{title,description}` → 204 |

### DRM 密钥分发

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/keys/{video_id}` | Bearer token | 返回 16-byte AES-128 内容密钥（Cache-Control: no-store）。需已登录 + 视频 approved+ready。未加密视频返回 404。 |

## 设计要点（对照设计文档）

1. **并行上传**：设计文档要求元数据与二进制走不同服务并行处理；本实现元数据在二进制落盘后注册（保证 `create_video` 校验二进制存在），时序上简化为顺序但接口边界保持分离。
2. **预签名 URL**：`presign.py` 模拟 S3 预签名——token 单次使用、TTL 300s、扩展名白名单、1GB 上限。
3. **转码 DAG**：Preprocessor 探测源并决定档位集合（≥1080p→3 档，≥720p→2 档），即设计文档中 DAG 的动态构建。
4. **Resource Manager**：每 Worker `asyncio.Semaphore(CONCURRENCY)` 限制并发编码，停机时 `drain()` 排空在途任务。
5. **错误分类**：坏文件（ffprobe 失败/无视频流）→ 不可恢复直接 failed；ffmpeg 瞬时失败 → 指数退避重试 3 次；worker 内部崩溃 → failed 事件兜底，视频可通过 retry 重入队。
6. **心跳机制**：Worker 每 15s 续期 `worker:{instance_id}`（TTL 60s）；`/api/stats` SCAN 该前缀统计在线实例。
7. **CDN 模拟**：nginx 只读挂载 `data/transcoded`，HLS 正确 MIME + CORS + 一年强缓存。
8. **单写者原则不变**：users 表与 videos/renditions 同在一个 SQLite，仍只有 api-server 写入。
9. **历史数据兼容**：`videos.uploader_id` 可空，用户系统上线前的视频显示为 Anonymous 且照常播放；迁移用 `PRAGMA table_info` 探测后再 `ALTER TABLE`，可重复执行。
10. **预签名归属校验**：`presign.claim_owner()` 一次性消费 `video_id → user_id` 映射，防止冒名注册他人上传的视频。
11. **角色层级前后端各一份**：后端 `app/auth/security.py` 的 `ROLE_LEVEL` 与前端 `src/auth.js` 的 `ROLE_LEVEL` 必须保持一致。
12. **评论读公开、写需登录**：列表/回复用 `get_optional_user`，登录才注入 `my_vote`；发表/投票用 `get_current_user`。
13. **1 级线程靠 root_id 归位**：回复的回复不新增层级，`root_id` 恒指向顶级评论，`parent_id` 记录“回复谁”。
14. **软删除保线程**：删除仅置 `status=deleted` 并屏蔽正文，回复链不断裂。
15. **反范式计数**：单写者事务内同步 `comment_votes` 与 `comments` 计数，排序走索引列，热读高效。
16. **Moderation status is orthogonal to transcode status** — `moderation_status` (pending_review/approved/rejected) is independent from `status` (pending/processing/ready/failed); a video is publicly visible only when `status='ready' AND moderation_status='approved'`.
17. **Visibility gate at API level, not CDN** — non-approved videos return 404; since video IDs are random hex, the CDN path is not guessable. True CDN-level auth is deferred to the DRM module.
18. **FIFO review queue** — videos enter moderation after transcode completes, oldest first; rejected videos re-enter queue via resubmit (no re-transcode).
19. **创建时生成密钥**：`POST /api/videos` 在 `insert_video` 后、`push_task` 前调用 `drm.generate_key`，确保 worker 拾取任务时 key file 已就位。密钥存储在 `data/keys/` 目录（api-server 和 worker 共享 volume，CDN 不挂载）。
20. **向后兼容**：存量视频无 key file → worker 不加密 → playlist 无 EXT-X-KEY → hls.js 正常播放明文路径。key endpoint 返回 404 不报错。
21. **hls.js xhrSetup 注入 Bearer**：播放器 fetch `/api/keys/...` 时自动附带 Authorization header，复用前端 token store（`getAccess()`）。Safari 原生 HLS 不支持此方式（已知限制）。

## 技术栈

FastAPI · aiosqlite · Redis (List 队列) · ffmpeg (HLS/x264/AAC) · nginx (CDN/反代) · Vue 3 · vue-router · axios · HLS.js · Docker Compose
