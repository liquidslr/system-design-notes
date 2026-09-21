# MyTube 视频 DRM（HLS AES-128 加密 + 密钥鉴权 + 可视水印）设计文档

**日期：** 2026-09-18
**系统：** MyTube（YouTube 风格视频流系统）
**状态：** 已确认，待实现

---

## 1. 背景与定位

### 1.1 上下文

MyTube 已有完整的用户认证、评论点赞、视频内容审核子系统。CDN 以 nginx 静态文件方式分发转码后的 HLS 分片，**不经过 api-server**，因此审核子系统无法对流媒体做 streaming-level 鉴权——拿到分片 URL 即可播放。本 DRM 子系统填补这一缺口。

### 1.2 目标

为**新上传并转码**的视频启用 HLS AES-128 加密，分片本身无法脱离密钥播放；密钥由 api-server 经鉴权后提供；前端叠加半透明可视水印起溯源/威慑作用。存量未加密视频保持原样、向后兼容。

### 1.3 非目标（本期明确不做）

- Widevine / FairPlay / PlayReady 等商业 DRM（需要 CDM + 专用 License Server）。
- 密钥轮换 / 过期策略（每视频一把静态密钥）。
- 服务端不可见（forensic）水印——需 per-session 动态封包，架构代价过高。
- CDN 配置变更（nginx.conf 不改——它 serve 的是加密后的分片，天然安全）。
- Safari 原生 HLS（无 `xhrSetup` 钩子注入 header，留为后续 cookie-session 增强）。
- 视频删除时密钥文件清理（留后续）。
- 新增容器、新增 pip 依赖。

---

## 2. 技术选型

| 技术 | 角色 | 选型理由 |
| --- | --- | --- |
| **ffmpeg `-hls_key_info_file`** | 转码时对 HLS 分片做 AES-128-CBC 加密 | ffmpeg 原生支持，零依赖；行业标准（HLS spec） |
| **HLS `#EXT-X-KEY`** | 在 playlist 中声明密钥 URI + IV | 所有 HLS 播放器（hls.js、VLC）均支持 |
| **Python `secrets.token_bytes(16)`** | 每个视频生成随机 16-byte AES 密钥 | stdlib，无新 pip |
| **api-server key delivery endpoint** | 鉴权后返回 raw key bytes | 无需新容器，集成在现有 FastAPI 路由中 |
| **hls.js `xhrSetup` callback** | 播放器 fetch key 时注入 Bearer token | hls.js 文档推荐方式 |
| **CSS 半透明 overlay** | 可视水印（用户名） | 纯前端，零后端改动 |

**关键约束**：不引入新 pip 包、不新增容器、不改 CDN 配置。所有新代码基于 stdlib + 已有依赖。

---

## 3. 架构与数据流

```
┌─────────── Viewer ─────────────┐
│ SPA :8080 → frontend nginx     │
│   /api/* → api-server:8000     │
│   /media/* → cdn:80            │
│ hls.js player + xhrSetup       │
│ CSS watermark overlay          │
└────────────────────────────────┘
      │ playlist (encrypted)         │ key (authenticated)
      ▼                              ▼
┌ cdn:80 ──────────────┐    ┌ api-server:8000 ─────────────┐
│ /media/{vid}/         │    │ GET /api/keys/{video_id}     │
│   master.m3u8         │    │ → auth (Bearer)              │
│   720p/seg_001.ts (enc)│   │ → assert_visible (approved)   │
│   (AES-128 encrypted) │    │ → read data/keys/{vid}.key   │
└───────────────────────┘    │ → 200 raw bytes, no-store     │
                              └──────────────────────────────┘

┌ worker ─────────────────────────────────────────┐
│ pipeline.process_video:                          │
│   if data/keys/{vid}.key exists:                 │
│     write {out_root}/key_info.txt                │
│     ffmpeg -hls_key_info_file key_info.txt       │
│   else:                                          │
│     (legacy path, no encryption)                 │
└──────────────────────────────────────────────────┘
```

- **Playlist URI 解析**：master.m3u8 中 `#EXT-X-KEY:URI="/api/keys/{vid}"`。浏览器从 `http://localhost:8080/media/...` 加载 playlist → 相对路径 `/api/keys/...` 解析为 `http://localhost:8080/api/keys/...` → frontend nginx 代理到 api-server。
- **CDN 无需改动**：serve 的是加密 .ts，无密钥无法解密。
- **存量视频兼容**：无 key file → worker 不传 `-hls_key_info_file` → playlist 无 EXT-X-KEY → hls.js 正常播放明文。

---

## 4. 密钥生命周期

```
创建视频 (POST /api/videos)
  │ secrets.token_bytes(16)
  ▼
写入 data/keys/{video_id}.key  ← 16 raw bytes on disk
  │
  │ worker 开始转码
  ▼
检测 key file 存在 → 写 key_info.txt (playlist URI + local path)
  │
  │ ffmpeg 加密
  ▼
产出 encrypted HLS (.ts + playlist with EXT-X-KEY)
  │
  │ 观众播放
  ▼
hls.js fetch /api/keys/{vid} with Bearer token
  │ api-server auth + moderation gate
  ▼
返回 16-byte key → hls.js decrypt → 播放
```

**幂等性**：
- `POST /api/videos` 对已有 key file 不重新生成（`if not exists`）。
- Worker 每次 transcode 重新写 `key_info.txt`（在 out_root，会被 rmtree 清除再重建）。
- 同一视频 retry 后使用同一密钥（key file 跨 retry 保留在 `data/keys/`）。

---

## 5. 后端设计

### 5.1 新文件 `app/drm.py`（路由模块）

```python
"""DRM: HLS AES-128 key generation and authenticated key delivery."""
import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Response
from app.auth.dependencies import get_current_user, CurrentUser
from app import database
from app.moderation.service import assert_visible, NotFoundError

router = APIRouter()

KEYS_DIR = os.getenv("KEYS_DIR", "data/keys")

def generate_key(video_id: str) -> None:
    """Generate AES-128 key for a video. Idempotent (skips if exists)."""
    path = os.path.join(KEYS_DIR, f"{video_id}.key")
    if os.path.exists(path):
        return
    os.makedirs(KEYS_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(secrets.token_bytes(16))

@router.get("/api/keys/{video_id}")
async def get_key(video_id: str, viewer: CurrentUser = Depends(get_current_user)):
    """Serve the AES-128 key for an encrypted video (authenticated)."""
    v = await database.get_video(video_id)
    if v is None:
        raise HTTPException(404, "video not found")
    try:
        assert_visible(v, viewer)
    except NotFoundError:
        raise HTTPException(404, "video not found")
    key_path = os.path.join(KEYS_DIR, f"{video_id}.key")
    if not os.path.exists(key_path):
        raise HTTPException(404, "video is not encrypted")
    with open(key_path, "rb") as f:
        key_bytes = f.read()
    return Response(content=key_bytes, media_type="application/octet-stream",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
```

### 5.2 server.py 改动

1. 在 `create_video` 中 upload-url 生成之后调用 `drm.generate_key(video_id)`。
2. `app.include_router(drm.router)` 注册路由。

### 5.3 Worker 改动

`worker/pipeline.py` 中 `process_video`：

```python
# After makedirs(out_root), before encoding:
key_file = os.path.join(os.getenv("KEYS_DIR", "data/keys"), f"{video_id}.key")
key_info_path = None
if os.path.exists(key_file):
    key_info_path = os.path.join(out_root, "key_info.txt")
    with open(key_info_path, "w") as f:
        f.write(f"/api/keys/{video_id}\n")
        f.write(f"{key_file}\n")
```

`worker/task_worker.py` 中 `_encode_once` 新增可选参数 `key_info_path=None`，条件添加 ffmpeg flag：
```python
if key_info_path:
    cmd.extend(["-hls_key_info_file", key_info_path])
```

`encode_rendition` 透传 `key_info_path`。

---

## 6. 前端设计

### 6.1 hls.js 配置（WatchView.vue `play()` 函数）

```javascript
function play(url) {
  const el = videoEl.value
  if (!el) return
  if (Hls.isSupported()) {
    const hls = new Hls({
      xhrSetup: (xhr, reqUrl) => {
        if (reqUrl.includes('/api/keys/')) {
          const token = authState.accessToken
          if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
        }
      }
    })
    hlsPlayer.value = hls
    hls.loadSource(url)
    hls.attachMedia(el)
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      levels.value = hls.levels.map((l, i) => ({ i, height: l.height }))
      hls.currentLevel = -1
    })
  } else if (el.canPlayType('application/vnd.apple.mpegurl')) {
    el.src = url
  }
}
```

### 6.2 可视水印

在 `<div class="player-box">` 内部 `<video>` 之后插入：

```html
<div v-if="authState.user" class="watermark">{{ authState.user.username }}</div>
```

### 6.3 CSS（style.css）

```css
.player-box { position: relative; }
.watermark {
  position: absolute; top: 8px; right: 12px;
  color: rgba(255, 255, 255, 0.35); font-size: 12px;
  pointer-events: none; z-index: 5; user-select: none;
}
```

注：`.player-box` 当前已有样式（`background: #000; ...`），只需追加 `position: relative`。

---

## 7. 配置与环境变量

| 变量 | 默认 | 服务 | 用途 |
|---|---|---|---|
| `KEYS_DIR` | `data/keys` | api-server, worker | 密钥文件存储目录 |

Docker Compose 中 api-server 和 worker 均挂载 `./data:/app/data`，因此 `data/keys/` 在两个容器内可达。CDN **不挂载** `data/keys/`（其 volume 仅 `data/transcoded:/usr/share/nginx/html/media`），密钥从架构上不可被 CDN 分发。

无需新增环境变量到 docker-compose.yml（使用默认值即可，容器内路径匹配挂载）。

---

## 8. 错误处理与边界情况

| 情况 | 响应 |
|---|---|
| 未认证（无 token） | 401 Unauthorized |
| 已认证但视频 pending_review/rejected | 404（伪装不存在，复用 assert_visible） |
| 视频存在但无 key file（legacy 未加密） | 404 "video is not encrypted" |
| Key file 读写错误（磁盘） | 500 |
| hls.js 播放中 key fetch 返回 401（token 过期） | hls.js ERROR 事件 → 前端 auth 拦截器刷新 token → 重试 fetch |
| Worker 找不到 key file（竞态/手动删除） | 不加密（graceful fallback，等同 legacy 路径） |
| 视频删除（leave for future） | key file 暂留磁盘，不影响功能 |

---

## 9. 测试策略

| 层面 | 方法 | 覆盖点 |
|---|---|---|
| 密钥生成 | 验证 `generate_key` → 文件存在 + 16 bytes | 正确性 |
| 密钥端点 | 单元：auth gates (401/404/403) + 正常返回 bytes | 鉴权 + 内容 |
| Worker 集成 | mock subprocess，验证 `-hls_key_info_file` 出现在 cmd 中（仅当 key 文件存在时） | 条件加密 |
| e2e 全链路 | 上传 → 转码 → playlist 含 EXT-X-KEY → authenticated key fetch → 16 bytes | 端到端 |
| 前端构建 | `npm run build` | 无语法错误 |
| 容器 | `docker compose up -d --build` → 5 Up | 无新容器 |
| 向后兼容 | 存量视频（无 key）仍正常转码+播放（无 EXT-X-KEY） | 不影响现有 |

---

## 10. 改动清单

**新增文件**
- `youtube-system/app/drm.py`（路由 + helper，约 50 行）

**修改文件**
- `youtube-system/app/server.py`（import drm + generate_key call + include_router）
- `youtube-system/worker/pipeline.py`（key file 检测 + key_info.txt 写入 + 传递 path）
- `youtube-system/worker/task_worker.py`（`_encode_once` + `encode_rendition` 接受 `key_info_path` 参数）
- `youtube-system/frontend/src/views/WatchView.vue`（Hls 配置 + watermark div）
- `youtube-system/frontend/src/style.css`（player-box position + watermark）
- `youtube-system/README.md`（DRM 特性 bullet + key endpoint 表 + 设计要点）

**不改的文件**
- `cdn/nginx.conf` — CDN 无需改动
- `docker-compose.yml` — 无需新容器/新环境变量
- `app/database.py` — 无新列/新表
- `app/config.py` — api-server config 无需新字段（路径用 `os.getenv("KEYS_DIR", "data/keys")`）
- `requirements.txt` — 不新增 pip 包
- `app/auth/` — 复用现有 dependencies/security
- `app/moderation/` — 复用 assert_visible + NotFoundError
