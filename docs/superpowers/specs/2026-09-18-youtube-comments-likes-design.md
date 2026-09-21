# MyTube 评论与点赞 设计规格

**日期**：2026-09-18
**范围**：为已实现的 `youtube-system`（含用户系统/登录/四级 RBAC）新增「视频评论 + 一层回复 + 评论赞/踩」。
**方案**：模块化单体——在现有 `api-server` 内新增 `app/comments/` 子包，不新增容器。

## 背景与范围界定

「用户系统/登录」已完成（`2026-09-17-youtube-user-auth-design.md`），是本轮的地基：评论需要评论者身份与既有 `ROLE_LEVEL` 权限。四功能拆解中本轮为第二轮「评论点赞」，与「视频内容审核」「DRM/水印加密」彼此独立。

**当前系统状态**：`app/auth/` 提供 `get_current_user`/`get_optional_user`/`require_role` 与 `ROLE_LEVEL`（user=1/creator=2/moderator=3/admin=4）；DB 有 `users`/`videos`/`renditions` 三表，api-server 为 SQLite **唯一写者**；前端 Vue3，`WatchView.vue` 展示单个视频，`api.js` 已封装 axios 实例与 Bearer/自动刷新拦截器。

## 1. 功能面（经澄清确认）

- 视频下有评论列表，支持**回复**
- 回复为 **1 级线程**（YouTube/微博式：顶级评论 + 其下一层回复；"回复的回复"扁平归入同一顶级线程）
- **投票只作用于评论**，采用**赞/踩互斥**（每人每评论一票，可切换、可取消），净分 `score = like_count - dislike_count`
- **不做视频级竖拇指/点踩**（本轮范围外）
- **读公开**（匿名可读）；**登录**（任意角色）才能评论/回复/投票
- **作者软删除**自己的评论（留「已删除」占位、其下回复保留）；**moderator/admin 可删除任意**评论
- 顶级评论默认按**净分**排序（同分按时间倒序），可切换「最新」；回复按时间正序；均用 `limit/offset` 分页
- 投票计数采用**反范式计数器**：`comments` 表冗余 `like_count/dislike_count/score`，投票时在同一连接事务内更新；`comment_votes` 表存每人每评论的票向。排序直接走冗余列，热读高效；单写者保证计数与投票表一致

## 2. 数据模型

新增两表，建表语句并入 `app/database.py` 的 `init_db()`（与既有表同一 `executescript`，`CREATE TABLE IF NOT EXISTS` 幂等，无需迁移）。

### 2.1 comments

```sql
CREATE TABLE IF NOT EXISTS comments (
    id            TEXT PRIMARY KEY,                    -- secrets.token_hex(12)
    video_id      TEXT NOT NULL REFERENCES videos(id),
    author_id     TEXT NOT NULL REFERENCES users(id),  -- 登录才能评论，作者恒存在
    parent_id     TEXT REFERENCES comments(id),        -- NULL=顶级；否则=被回复的那条评论id
    root_id       TEXT REFERENCES comments(id),        -- 所属顶级评论id；顶级自身为 NULL
    body          TEXT NOT NULL,                       -- 去首尾空白后 1..1000 字符
    status        TEXT NOT NULL DEFAULT 'active',      -- active | deleted(软删占位)
    like_count    INTEGER NOT NULL DEFAULT 0,
    dislike_count INTEGER NOT NULL DEFAULT 0,
    score         INTEGER NOT NULL DEFAULT 0,          -- 冗余净分 = like_count - dislike_count
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_thread ON comments(root_id, status);
CREATE INDEX IF NOT EXISTS idx_comments_sort   ON comments(video_id, status, score, created_at);
```

### 2.2 comment_votes

```sql
CREATE TABLE IF NOT EXISTS comment_votes (
    user_id    TEXT NOT NULL REFERENCES users(id),
    comment_id TEXT NOT NULL REFERENCES comments(id),
    value      INTEGER NOT NULL,                       -- +1 赞 / -1 踩
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, comment_id)                  -- 每人每评论最多一票，天然幂等
);
CREATE INDEX IF NOT EXISTS idx_votes_comment ON comment_votes(comment_id);
```

### 2.3 1 级回复的落库规则

创建时接收可选 `reply_to`（被回复评论的 id）：

| 情形 | parent_id | root_id |
|------|-----------|---------|
| 无 `reply_to`（顶级） | `NULL` | `NULL` |
| `reply_to` 指向顶级评论（其 `parent_id IS NULL`） | `reply_to.id` | `reply_to.id` |
| `reply_to` 指向某条回复（其 `parent_id NOT NULL`） | `reply_to.id`（保留"回复 @谁"上下文） | `reply_to.root_id`（归入同一顶级线程） |

约束：`reply_to` 指向的评论必须存在且 `video_id` 与路径参数一致，否则 404/400。展示恒为「顶级 + 一层回复」，线程成员用 `root_id` 聚合。

## 3. 模块结构

```
app/comments/
├── __init__.py
├── schemas.py   # CommentCreateRequest / VoteRequest / CommentOut 等
├── service.py   # 建评论/回复、投票、列表、软删业务逻辑；抛领域异常
└── router.py    # /api 端点；领域异常 → HTTP 状态码
```

- 依赖方向单向：`router → service → (database)`；鉴权直接复用 `app.auth.dependencies`（`get_current_user`、`get_optional_user`）与 `app.auth.security.ROLE_LEVEL`，**不复制角色常量**。
- `app/server.py` 仅新增 `app.include_router(comments_router)`，无 lifespan 改动（两表随 `init_db()` 建立）。
- 沿用 `app/auth/service.py` 的领域异常命名风格：`NotFoundError`(404)/`ValidationError`(400)/`PermissionDenied`(403)。若需要新异常类型，置于本模块 `service.py`，不改 `app/auth`。

## 4. API 端点

所有路径前缀 `/api`。分页参数 `limit`（默认 20，`1..50`）、`offset`（默认 0，`≥0`）。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/videos/{video_id}/comments` | 公开（可选登录） | 顶级评论分页；`?sort=top\|new`（默认 `top`）；登录则每条附 `my_vote` |
| GET | `/comments/{comment_id}/replies` | 公开（可选登录） | 该顶级线程的回复，时间正序分页；`comment_id` 须为顶级 |
| POST | `/videos/{video_id}/comments` | 登录 | body `{content, reply_to?}` → 建评论或回复，返回 CommentOut |
| DELETE | `/comments/{comment_id}` | 作者本人 或 moderator+ | 软删除，返回 204 |
| PUT | `/comments/{comment_id}/vote` | 登录 | body `{value}`，`value∈{1,-1,0}`（0=撤票）；返回该评论最新计数与 `my_vote` |

### 4.1 鉴权注入

- 读接口用 `get_optional_user`：匿名 `user=None`，`my_vote` 恒为 `0`；登录用户 LEFT JOIN `comment_votes` 注入其票向（+1/-1/0）。
- 写接口用 `get_current_user`（401 未登录）。
- `DELETE` 用 `get_current_user`，服务层判定 `author_id == user.id || ROLE_LEVEL[user.role] >= ROLE_LEVEL["moderator"]`，否则 403（与既有 retry 端点的 `is_owner/is_staff` 风格一致）。

### 4.2 CommentOut 响应结构

```json
{
  "id": "…", "video_id": "…",
  "author": {"id": "…", "username": "…"},
  "content": "…", "status": "active",
  "parent_id": null, "root_id": null,
  "like_count": 3, "dislike_count": 1, "score": 2,
  "reply_count": 5, "my_vote": 1, "created_at": 1789000000.0
}
```

- `status="deleted"` 时：`content` 固定占位文案（如 "This comment was deleted."），`author` 仅保留 `{id:null, username:"deleted"}` 之一（不泄露原作者与原文）；`reply_count`/`my_vote` 照常。
- 顶级列表附 `reply_count`；回复列表 `reply_count` 可为 0（不再嵌套计数）。

## 5. 服务逻辑要点

### 5.1 建评论/回复
1. `content.strip()` 后校验长度 1..1000，否则 400。
2. 校验 `video_id` 存在（`database.get_video`），否则 404。
3. 若带 `reply_to`：取目标评论，校验存在、属于同一 video、且其 `status=active`（不可回复已删除）；按 §2.3 计算 `parent_id/root_id`。
4. `insert_comment`，返回完整 CommentOut（`my_vote=作者自己的票，默认 0`）。

### 5.2 投票 `apply_vote`（单事务）
- 校验 `value∈{1,-1,0}`；评论存在且 `status=active`，否则 404/400。
- 读旧票 `old∈{None,+1,-1}`，与 `value` 比较：
  - `value == old` → **幂等 no-op**（不改计数）。
  - `value == 0` → 删除票行；旧票对应计数 −1。
  - 否则（新增或切换）：新 `value` 计数 +1；若 `old` 非空则旧计数 −1；写/更新票行。
- 重算 `score = like_count - dislike_count` 并更新 `comments`。
- 返回 `{like_count, dislike_count, score, my_vote: value}`。

`database.py` 内以单个 `async with aiosqlite.connect(...)` 事务包裹「读旧票→改 comment_votes→改 comments 计数」，保证一致性（单写者无并发竞争）。

### 5.3 列表/回复
- 顶级：`WHERE video_id=? AND parent_id IS NULL`，`deleted` 仍返回（占位）；`sort=top` → `ORDER BY score DESC, created_at DESC`；`sort=new` → `ORDER BY created_at DESC`；`LIMIT ? OFFSET ?`。子查询/二次查询得 `reply_count`（该 root 下 `status=active` 回复数）。
- 回复：`WHERE root_id=? AND (status='active' OR status='deleted')`，`ORDER BY created_at ASC`，分页；`comment_id` 必须是顶级评论（`parent_id IS NULL`），否则 404。
- 列表响应附 `{comments:[…], total, has_more}`（`total` 为该视频顶级评论总数或该线程回复总数）。

## 6. 前端改造

- **`api.js`** 追加：`listComments(videoId, {sort,limit,offset})`、`listReplies(commentId, {limit,offset})`、`createComment(videoId, content, replyTo?)`、`deleteComment(commentId)`、`voteComment(commentId, value)`。复用既有 `http` 实例与 `extractError`；Bearer 注入与 401 自动刷新对评论请求同样生效（`/api/comments*` 非 auth 端点，正常带 token）。
- **抽独立组件**（`WatchView.vue` 已约 130 行，避免继续膨胀）：
  - `components/Comments.vue`：发表框、`Top/Newest` 排序切换、顶级列表、分页"加载更多"。
  - `components/CommentItem.vue`：单条评论——作者/时间/正文、赞/踩按钮（显示计数、`my_vote` 高亮、点击切换/取消）、回复内联输入框、对作者或 moderator+ 显示删除按钮、可展开该线程回复。
  - `WatchView.vue` 播放器与信息下方挂 `<Comments :video-id="route.params.id" />`。
- **登录门控**：`authState.user` 为空时发表框替换为「Sign in to comment」链接 `/login?redirect=<当前路径>`；匿名点击赞/踩同样引导登录。删除按钮可见性用 `auth.js` 的 `hasRole('moderator')` 或 `comment.author.id === authState.user?.id` 判定。
- **样式**：`frontend/src/style.css` 末尾追加评论区块样式，复用既有 CSS 变量（`--bg-card/--border/--text/--text-dim/--accent`）。
- **无路由/守卫改动**：评论内嵌在 Watch 页，公开可读。

## 7. 错误处理与边界

- 视频不存在 → 404；评论不存在 → 404；对已删除评论回复/投票 → 400。
- `limit>50` → 422（Pydantic 约束）；`value∉{1,-1,0}` → 422。
- 未登录写操作 → 401；非作者且非 moderator+ 删除 → 403。
- `reply_to` 跨视频 → 400。
- 删除顶级评论仅软删自身，其回复保留并可继续显示（线程不因删除而断）。
- 幂等：同一用户重复提交相同 `value` 不重复计数；重复删除已删除评论为 no-op（仍 204 或返回已删）。

## 8. 测试策略

### 8.1 纯逻辑验证（临时 `_verify_*.py`，跑完即删）
用临时文件 SQLite 直连 `service`+`database`（不依赖 Redis/容器）覆盖：
1. 建顶级评论与回复；回复的回复归位到同一 `root_id`。
2. 投票：新增/切换/取消/幂等四态的 `like_count/dislike_count/score` 数学正确。
3. `sort=top` 按 score 再时间；`sort=new` 按时间。
4. 分页 `limit/offset` 与 `has_more`。
5. 软删除权限矩阵：作者可删、他人 403、moderator/admin 可删任意；deleted 投影屏蔽正文。
6. `my_vote` 注入：登录查询返回本人票向，匿名为 0。
7. 回复按时间正序。
8. 跨视频 `reply_to`、对 deleted 评论回复/投票被拒。

### 8.2 后端 e2e（对运行中的容器）
注册→登录→（creator 角色）上传并等 ready 拿 `video_id`→评论→回复→赞/踩/切换/取消→顶级列表→回复列表→他人删除 403→作者删除→moderator 删除。断言 HTTP 码、计数与投影字段。

### 8.3 前端
`npm run build` 通过 + 重建 frontend 容器 + 浏览器人工清单（匿名可读、登录可评论/回复/投票、赞踩高亮与计数、删除按钮可见性、分页/排序切换、软删占位）。

## 9. 明确不做（本轮范围外）

- 评论机审/人审队列、敏感词过滤（属后续「视频内容审核」独立模块）
- 无限嵌套树（仅 1 级）
- 视频级点赞/点踩（本轮只作用于评论）
- 编辑评论、@提及与通知、图片/富文本评论
- 评论实时推送/轮询、评论搜索、个性化热榜算法
- 防刷/限流（沿用现有策略，不单独实现）
