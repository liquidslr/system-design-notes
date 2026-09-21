# YouTube 视频流系统设计规格

日期：2026-09-17
依据：《System Design Interview》第 14 章（14. Youtube/Readme.md）

## 1. 目标与范围

实现一个 YouTube 风格的视频上传-转码-流媒体播放系统，完整演示设计文档的核心流程：

- 视频上传流程（二进制上传与元数据提交并行）
- 转码流水线（Preprocessor → DAG Scheduler → Resource Manager → Task Workers）
- 流媒体播放（HLS 自适应码率，多分辨率画质切换）
- 系统优化（Pre-Signed URL 上传鉴权、消息队列解耦、Worker 水平扩展）

不在范围内：DRM/水印加密、用户系统/登录、评论点赞、视频内容审核。

## 2. 技术选型（已确认）

| 决策点 | 选择 |
|--------|------|
| 转码 | 真实 ffmpeg（Docker 内 apt 安装），产出标准 HLS 多码率产物 |
| 架构 | 微服务多容器（api-server / transcoder-worker / cdn / frontend / redis） |
| 任务队列 | Redis List（transcode:tasks / transcode:done），Worker 用 BLPOP 阻塞消费 |
| 前端 | Vue 3 + Vite + HLS.js 完整前端 |
| 存储 | 本地卷模拟 blob storage；元数据用 SQLite（apiosqlite） |

沿用项目既有模式：FastAPI + Pydantic + Python 3.11 + Docker Compose + npm npmmirror 镜像 + pip 清华镜像。

## 3. 服务编排（5 容器）

| 服务 | 端口 | 职责 |
|------|------|------|
| frontend | 8080→80 | Vue 3 SPA；nginx 将 /api/* 反代 api-server:8000，/media/* 反代 cdn:8003 |
| api-server | 8000 | 预签名 URL、接收上传、元数据 CRUD、入队任务、消费完成队列、统计 |
| transcoder-worker | 8001（health，仅内部） | BLPOP 消费任务，执行 ffmpeg 转码 DAG；可 --scale N 水平扩展（不映射宿主端口以免冲突） |
| cdn | 8003→80 | 只读 nginx，root 指向 transcoded-storage 卷，HLS MIME 支持 |
| redis | 6379 | transcode:tasks 任务队列、transcode:events 事件队列（processing/ready/failed） |

共享卷：`./data/original`（原始视频）、`./data/transcoded`（转码产物），由 api-server、transcoder-worker、cdn 三方挂载。

## 4. 数据模型（SQLite，2 表）

```sql
videos(
  id TEXT PRIMARY KEY,            -- uuid4 hex
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  status TEXT NOT NULL,           -- pending | processing | ready | failed
  original_path TEXT,             -- 相对 original-storage 的文件名
  duration_sec REAL,
  width INTEGER, height INTEGER,
  error_msg TEXT,
  created_at REAL, updated_at REAL
)
renditions(
  id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES videos(id),
  resolution TEXT NOT NULL,       -- 1080p | 720p | 480p
  playlist_path TEXT,             -- transcoded-storage 内相对路径
  bitrate_kbps INTEGER,
  status TEXT NOT NULL,           -- pending | processing | done | failed
  UNIQUE(video_id, resolution)
)
```

状态机：
- videos：pending →（Worker 接收任务后置）processing →（完成队列消费后）ready；不可恢复错误或重试超限 → failed；retry 接口 → processing
- renditions：pending → processing（Worker 开始编码该档位时置）→ done / failed

## 5. API 设计（api-server）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/upload-url | 生成预签名 token（uuid + 300s 过期，内存表），body: {filename, size, content_type}；校验扩展名 ∈ {mp4, mov, avi, mkv, webm}；响应 {token, video_id, expires_in}（video_id 由服务端生成，后续上传/元数据接口均用它） |
| POST | /api/upload/{token} | 流式接收二进制（≤1GB）写 original-storage/{video_id}.ext；校验 token 有效性/过期 |
| POST | /api/videos | 提交元数据 {video_id, title, description}；置 pending；生成 renditions 行；LPUSH transcode:tasks |
| GET | /api/videos | 列表：含 thumbnail_url（若已有）、status |
| GET | /api/videos/{id} | 详情：ready 时返回 {stream_url: /media/{id}/master.m3u8, renditions[]} |
| POST | /api/videos/{id}/retry | failed→processing：重置 renditions 为 pending，重新入队 |
| GET | /api/stats | 队列深度（LLEN）、Worker 数、各状态视频计数 |

完成队列消费：Worker 不直接写 SQLite（保持单写者）。Worker 推送事件到 transcode:events：processing（含 ffprobe 元数据与档位集合，消费端据此创建 renditions 行）、ready（含各档位 playlist 路径）、failed（含错误信息）。api-server lifespan 启动后台协程 BLPOP 该队列（timeout 2s 循环），按事件更新 videos/renditions。

预签名安全（设计文档 Safety Optimizations）：上传前必须先获取 token；token 单次有效、300 秒过期、绑定 video_id；无效/过期 token 返回 403。

Worker 心跳：每个 Worker 实例周期性 SET `worker:{instance_id}`（TTL 60s），/api/stats 通过 SCAN 统计存活 Worker 数。

## 6. 转码流水线（transcoder-worker）

任务消息 JSON：{video_id, original_path, title}

四层结构（对应设计文档 Video Transcoding Architecture）：

1. **Preprocessor**
   - ffprobe -v quiet -print_format json -show_format -show_streams 提取元数据
   - 校验含视频流，否则直接 failed（不可恢复错误）
   - 依据源高度筛选档位：≥1080 生成 [1080p,720p,480p]；≥720 生成 [720p,480p]；其余 [480p]
   - 更新 videos.duration/width/height；renditions 置 processing

2. **DAG Scheduler**
   - Stage 1：thumbnail（ffmpeg -ss 1 -i 源 -vframes 1 thumbnail.jpg）
   - Stage 2：N 个分辨率档位编码任务（相互独立，并行）
   - 每阶段完成后汇报，全部完成推完成事件

3. **Resource Manager**（进程内）
   - task_queue：asyncio.Queue 存放当前 DAG 任务
   - worker_pool：asyncio.Semaphore(2) 限制并发 ffmpeg 进程数（每容器 2 并发）
   - running_tasks：{task_id: asyncio.Task}，供 /api/stats 与优雅停机（shutdown 时取消并等待）

4. **Task Worker**
   - 单档位命令：ffmpeg -i 源 -vf scale=-2:1080 -c:v libx264 -crf 23 -preset veryfast -c:a aac -b:a 128k -hls_time 4 -hls_playlist_type vod -hls_segment_filename seg_%03d.ts 1080p/playlist.m3u8
   - master.m3u8 由代码生成（EXT-X-STREAM-INF 按 BANDWIDTH/RESOLUTION 排序）
   - 可恢复错误：进程非零退出 → 重试（最多 3 次，指数退避 2^n 秒）；超限 → renditions failed → video failed
   - 不可恢复：ffprobe 解析失败 → 直接 failed

完成事件 JSON（推送到 transcode:events）：
- processing：{video_id, type, duration_sec, width, height, renditions: [{resolution, bitrate_kbps}]}
- ready：{video_id, type, renditions: [{resolution, playlist_path, bitrate_kbps}]}
- failed：{video_id, type, error}

健康端点：GET /health（供 compose healthcheck）。

## 7. CDN（模拟）

nginx 配置：root /usr/share/nginx/html（挂载 transcoded-storage 卷）；
location ~ \.m3u8$ { types { application/vnd.apple.mpegurl; } }；
location ~ \.ts$ { types { video/mp2t; } }；add_header Access-Control-Allow-Origin *（HLS.js 跨域需要）。

## 8. 前端设计（Vue 3）

| 视图 | 功能 |
|------|------|
| HomeView | 视频网格卡片（thumbnail / 标题 / 状态徽章 / 时长）；5 秒轮询刷新状态 |
| UploadView | 拖拽选文件 + 标题/描述表单；流程：POST /api/upload-url → 并行 [POST /api/upload/{token}（axios onUploadProgress 进度条）, POST /api/videos] → 成功跳转首页 |
| WatchView | HLS.js 播放 master.m3u8，自定义画质菜单列出 hls.levels（1080p/720p/480p，可选自动）；processing 时显示“转码中”轮询；failed 显示错误与重试按钮 |

路由：vue-router（/ 、/upload、/watch/:id）。依赖：vue、vue-router、axios、hls.js。

## 9. 错误处理汇总

| 类别 | 场景 | 处理 |
|------|------|------|
| 不可恢复 | ffprobe 无法解析/无视频流 | video failed，记录 error_msg，不入重试 |
| 可恢复 | 单档位 ffmpeg 非零退出 | 重试 ≤3 次（退避 2/4/8s），超限 failed |
| 上传安全 | token 无效/过期 | 403，提示重新获取 |
| 上传超限 | 文件 >1GB 或非法扩展名 | 400 |
| Worker 崩溃 | 容器重启 | 任务仍留 Redis 队列（BLPOP 未确认即重启会重取），幂等：转码前清理旧产物目录 |

## 10. 验证计划

1. `docker compose up --build --scale transcoder-worker=2`
2. ffmpeg 现场生成测试视频（如 testsrc 10 秒 1080p）→ 前端上传
3. 验证状态流转 pending → processing → ready（首页轮询可见）
4. 播放页验证 HLS 播放 + 手动切换 1080p/720p/480p
5. 上传一个损坏文件验证 failed 状态与错误提示
6. 对 failed 视频调用 retry 接口验证恢复
7. curl 验证 CDN 直接可拉取 /media/{id}/master.m3u8 与 .ts 分片
