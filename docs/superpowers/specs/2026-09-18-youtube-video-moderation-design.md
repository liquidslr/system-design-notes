# MyTube 视频内容审核 设计规格

**日期**：2026-09-18  
**范围**：为 `youtube-system` 新增视频内容审核——转码完成后进入待审队列，moderator 通过后方公开。  
**方案**：模块化单体——在现有 `api-server` 内新增 `app/moderation/` 子包，不新增容器、不新增 pip 依赖。

## 背景与定位

四功能拆解第三轮（前两轮：①用户系统、②评论点赞 已完成）。本模块为视频增加先审后发机制：

```
用户系统/登录  ✅
    ├── 评论点赞      ✅
    ├── 视频内容审核  ←── 本轮
    └── DRM/水印加密  （后续）
```

## 功能边界

| 包含 | 明确不做 |
|------|----------|
| 手动审核队列（moderator 通过/拒绝） | 自动/ML 判定、关键词匹配 |
| 转码完成后才进入队列 | 审核历史/审计日志 |
| 先审后发（未通过不对公众可见） | 账号 strike 升级机制 |
| 拒绝可编辑元数据后重新提交 | 申诉流程 |
| 仅视频（评论审核延后） | CDN 分片字节级鉴权（属 DRM） |

## 1. 数据模型

### 1.1 videos 表扩展

在 `init_db()` 中通过 PRAGMA 探测幂等 ALTER：

```sql
ALTER TABLE videos ADD COLUMN moderation_status TEXT NOT NULL DEFAULT 'approved';
ALTER TABLE videos ADD COLUMN rejection_reason  TEXT;
```

- **存量视频**默认 `approved`（迁移不消失）
- **新上传**由 `insert_video` 显式写入 `'pending_review'`
- `status`（转码态：pending→processing→ready/failed）与 `moderation_status` 完全正交

### 1.2 可见性规则

```
公开可见 ⟺ status = 'ready' AND moderation_status = 'approved'
```

### 1.3 新增索引

```sql
CREATE INDEX IF NOT EXISTS idx_videos_public
    ON videos(status, moderation_status, created_at);
```

用于 Home 列表 (`list_videos_public`) 和审核队列查询。

### 1.4 database.py 新增/修改函数

```python
# 新函数
async def list_videos_public(limit: int, offset: int) -> list[dict]
async def count_videos_public() -> int
async def list_moderation_queue(limit: int, offset: int) -> list[dict]
async def count_moderation_queue() -> int
async def set_moderation(video_id: str, status: str, reason: str | None) -> None
async def resubmit_video(video_id: str, title: str, description: str) -> None

# 修改
async def insert_video(...)   # 写入时设置 moderation_status='pending_review'
```

- `list_videos_public`：`WHERE status='ready' AND moderation_status='approved' ORDER BY created_at DESC`，带分页
- `list_moderation_queue`：`WHERE status='ready' AND moderation_status='pending_review' ORDER BY created_at ASC`（先进先审）
- `set_moderation`：UPDATE moderation_status + rejection_reason
- `resubmit_video`：UPDATE title, description, moderation_status='pending_review', rejection_reason=NULL
- `insert_video`：`ON CONFLICT` 分支也加 `moderation_status='pending_review'`

## 2. API 端点

### 2.1 新增审核端点（`app/moderation/router.py`）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/moderation/queue` | moderator+ | 待审列表 `{videos, total}`，query: limit/offset |
| POST | `/api/moderation/{video_id}/approve` | moderator+ | → approved |
| POST | `/api/moderation/{video_id}/reject` | moderator+ | body: `{reason: str(min1,max500)}` → rejected |

### 2.2 新增上传者端点（`app/server.py` 或 `app/moderation/router.py`）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/videos/{video_id}/resubmit` | owner | body: `{title, description}` → pending_review |

放在 moderation router 内，因为属审核工作流一部分（与 retry 对称）。

### 2.3 现有端点行为变更

| 端点 | 变更 |
|------|------|
| `GET /api/videos` | 改调 `list_videos_public`（仅 ready+approved），附分页 total |
| `GET /api/videos/{id}` | 非 approved+ready 时：owner 或 moderator+ 可看（附 moderation_status/rejection_reason），其他人 404 |
| `GET /api/videos/mine` | 返回所有自己的视频（含 pending_review/rejected），附 moderation_status/rejection_reason |
| `stream_playlist` | 同 get_video 门控逻辑 |
| `_card` 辅助 | 添加 `moderation_status` 字段到返回值 |

## 3. 模块结构

```
app/moderation/
├── __init__.py       # docstring
├── schemas.py        # RejectRequest(reason), ResubmitRequest(title, description), ModerationOut(...)
├── service.py        # approve / reject / resubmit / list_queue / assert_visible
└── router.py         # /api/moderation/* 与 /api/videos/{id}/resubmit 端点
```

依赖方向：`router → service → database`。  
鉴权复用 `app.auth.dependencies`（`require_role("moderator")`、`get_current_user`）和 `app.auth.security.ROLE_LEVEL`。  
`server.py` 仅 `app.include_router(moderation_router)`。

`service.py` 抛领域异常（NotFoundError / PermissionDenied / ValidationError），`router.py` 映射 HTTP 码。

### 3.1 service 核心逻辑

```python
async def list_queue(limit, offset) -> dict:
    videos = await database.list_moderation_queue(limit, offset)
    total = await database.count_moderation_queue()
    return {"videos": [...], "total": total}

async def approve(video_id, actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None: raise NotFoundError("video not found")
    if v["moderation_status"] != "pending_review":
        raise ValidationError("only pending_review videos can be approved")
    await database.set_moderation(video_id, "approved", None)

async def reject(video_id, reason: str, actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None: raise NotFoundError("video not found")
    if v["moderation_status"] != "pending_review":
        raise ValidationError("only pending_review videos can be rejected")
    await database.set_moderation(video_id, "rejected", reason)

async def resubmit(video_id, title, description, actor: CurrentUser) -> None:
    v = await database.get_video(video_id)
    if v is None: raise NotFoundError("video not found")
    if v["uploader_id"] != actor.id:
        raise PermissionDenied("not your video")
    if v["moderation_status"] != "rejected":
        raise ValidationError("only rejected videos can be resubmitted")
    await database.resubmit_video(video_id, title, description)

def assert_visible(video: dict, viewer: CurrentUser | None) -> None:
    """Gate for GET video / stream_playlist:
    If not approved+ready → only owner or moderator+ can view, else 404."""
    is_public = video["status"] == "ready" and video["moderation_status"] == "approved"
    if is_public: return
    # Not public — check viewer
    if viewer is None:
        raise NotFoundError("video not found")
    is_owner = video.get("uploader_id") == viewer.id
    is_staff = ROLE_LEVEL.get(viewer.role, 0) >= ROLE_LEVEL["moderator"]
    if not (is_owner or is_staff):
        raise NotFoundError("video not found")
```

## 4. 审核状态机

```
                ┌─────────────────────────────────────┐
                │                                     │
  upload → pending_review → approved  (visible)       │
                ↑                │                    │
                │                ↓                    │
             resubmit ←── rejected (invisible)        │
                                │                     │
                                └── (retry = transcode failure, not here)
```

- `pending_review`：转码完成 (`status='ready'`) 后进入
- `approved`：本轮终态（仅由 pending_review 转入）
- `rejected`：可 resubmit 回 pending_review

**撤回已发布**：本轮不支持 moderator 事后下架已 approved 的视频（approve/reject 仅接受 `pending_review` 状态，见 §3.1 校验）。留为后续增强。本轮流转为 `pending_review → approved/rejected`，加 `rejected → pending_review`（resubmit）。

## 5. 前端集成

### 5.1 新增路由与导航

- `/moderation` → `ModerationView.vue`，meta: `{ requiresAuth: true, role: 'moderator' }`
- 导航栏：与 Admin Users 同级，`hasRole('moderator')` 显示「审核」入口

### 5.2 api.js 新函数

```js
export function listModerationQueue(limit = 50, offset = 0)
export function approveVideo(videoId)
export function rejectVideo(videoId, reason)
export function resubmitVideo(videoId, title, description)
```

### 5.3 ModerationView.vue（审核台）

- 列表展示待审视频（标题 + 上传者 + 缩略图 + 上传时间）
- 点击可弹出预览（iframe 或直接跳转 WatchView 带 moderator 标记）
- 每条有 Approve / Reject 按钮；Reject 弹出输入 reason
- 分页 / 刷新

### 5.4 MyVideosView.vue 变更

- 每条视频卡片增加状态标签：审核中 (pending_review)、已拒绝 (rejected + reason tooltip)
- rejected 视频旁显示 "Resubmit" 按钮 → 弹出编辑标题/描述 → 调 resubmitVideo

### 5.5 WatchView.vue 变更

- 若视频未 approved+ready（通过 moderation_status 字段判断），播放器区域显示状态横幅（"审核中"/"已被拒绝：reason"）而非播放器

### 5.6 HomeView.vue

- 无需改动（后端已过滤，前端收到的列表全是 approved+ready）

## 6. 配置与依赖

- **无新增 pip 包**
- **无新增环境变量**（复用 JWT_SECRET/ACCESS_TOKEN_TTL 等已有认证配置）
- **无新增 Docker 容器**（审核逻辑在 api-server 内运行）

## 7. 错误处理

| 异常 | HTTP | 场景 |
|------|------|------|
| NotFoundError | 404 | 视频不存在 / 非 approved 且 viewer 无权限（伪装 404） |
| PermissionDenied | 403 | resubmit 非本人 |
| ValidationError | 400 | 状态不符（非 pending_review 就 approve/reject；非 rejected 就 resubmit） |
| Pydantic 422 | 422 | RejectRequest.reason 为空/超长；ResubmitRequest 字段校验 |

## 8. 验证计划

临时脚本 + 容器 e2e + npm build，与评论点赞子系统相同验证模式：

1. `_verify_moderation_db.py`：建表 → insert_video 写 pending_review → set_moderation 切状态 → list_videos_public 门控 → list_moderation_queue → resubmit_video → 断言全路径
2. `_verify_moderation_routes.py`：import app.server 遍历 routes 确认端点注册 + 权限依赖
3. `_e2e_moderation.py`：对运行容器 HTTP 走完整流程（注册→上传→审核通过→列表可见→拒绝→resubmit→403/404/400 边界）
4. `npm build` 前端编译通过
5. `docker compose up -d --build` 五容器 Up + health ok

## 9. 设计约束与已知限制

- api-server 仍是 SQLite 唯一写者（审核写操作也在 api-server 内）
- CDN 分片不做鉴权：已知 approved 视频的 URL 一旦被分享即无法撤回（属 DRM 模块）
- 审核队列 FIFO（按 created_at ASC）：不实现优先级/分类标签（YAGNI）
- 转码中 (status≠ready) 的视频不进入队列（无内容可审）
- 并发审核：无锁（SQLite 单写者天然串行，后到操作覆盖）
