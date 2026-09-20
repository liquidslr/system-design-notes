# Google Drive — Cloud File Storage & Sync System

基于 [Chapter 15: Design Google Drive](../15.%20Google%20Drive/Readme.md) 系统设计文档的可运行实现。

## Features

| 设计概念 | 实现方式 |
|---------|---------|
| 4MB 内容寻址分块 | `BlockServer.split()` + SHA-256 哈希 |
| 块级去重 (De-duplication) | `ObjectStore.put_if_absent()` + `blocks.ref_count` |
| 断点续传 (Resumable Upload) | `upload_sessions` 表 + 状态查询 + 仅补缺失块 |
| Delta 同步 | 客户端上报块清单 → 服务端只接收缺失块 |
| 文件版本历史 | `file_versions` 表存储每版有序块列表 |
| 同步冲突解决 | 乐观并发控制 (base_version vs latest_version) → 409 + 双版本保留 |
| 共享与权限 | `shares` 表 (view/edit) + 下载/编辑权限校验 |
| 通知服务 (长轮询) | `asyncio.Event` 即时唤醒 + DB `delivered` 离线队列 |
| 配额限制 | 10GB/user，commit 时校验 used_bytes + new_unique_bytes |
| 存储优化 & GC | `ref_count == 0` 块由 `/api/admin/gc` 回收 |
| 冷存储标记 | `files.storage_class` 列 (hot/cold) |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI Server (server.py)                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  ApiService (api_service.py) — Core Business Logic        │  │
│  │  ┌────────────────┐ ┌──────────────┐ ┌──────────────────┐ │  │
│  │  │  Block Server  │ │  Database    │ │ Notification Ctr │ │  │
│  │  │  (block_server)│ │  (SQLite)    │ │ (asyncio.Event)  │ │  │
│  │  └───────┬────────┘ └──────────────┘ └──────────────────┘ │  │
│  │          │                                                 │  │
│  │  ┌───────▼────────┐                                       │  │
│  │  │  Object Store  │  (local dir = S3 simulation)          │  │
│  │  │ data/blocks/   │                                       │  │
│  │  └────────────────┘                                       │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install dependencies

```powershell
cd google-drive
pip install -r requirements.txt
```

### 2. Run Demo (no server needed)

```powershell
python __main__.py --demo
```

输出完整故事线：注册→上传→去重→编辑→冲突→解决→共享→通知→统计。

### 3. Run API Server

```powershell
python __main__.py --server
# Server starts on http://0.0.0.0:9200
```

### 4. Use CLI Client

```powershell
python cli.py register alice@example.com password123
python cli.py upload ./mylargefile.bin
python cli.py list
python cli.py download f_xxxxxxxx output.bin
python cli.py share f_xxxxxxxx bob@example.com edit
python cli.py notifications --wait 5
python cli.py stats
python cli.py gc
```

### 5. Run Tests

```powershell
python -m pytest tests/ -v
```

24 个单元测试覆盖：分块/去重/断点续传/delta/冲突/通知/配额/GC。

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/register` | Create user |
| POST | `/api/login` | Get session token |
| GET | `/api/files/list` | List user's files |
| POST | `/api/files/upload` | Start resumable upload |
| POST | `/api/blocks` | Upload batch of blocks |
| GET | `/api/sessions/{id}` | Query upload status |
| POST | `/api/files/{id}/commit` | Commit upload as new version |
| GET | `/api/files/{id}/download` | Download file (reassemble blocks) |
| GET | `/api/files/{id}/revisions` | List revision history |
| POST | `/api/sync` | Sync client state → updates/conflicts |
| POST | `/api/files/{id}/resolve` | Resolve conflict (override/keep) |
| POST | `/api/files/{id}/share` | Share file with user |
| GET | `/api/notifications` | Long-poll for events |
| POST | `/api/admin/gc` | Garbage-collect orphan blocks |
| GET | `/api/stats` | System statistics |

## Design Decisions

1. **Single process, layered roles** — 用模块边界分离 Block Server / API Server / Object Store，而非多进程/容器。适合学习且易于测试。
2. **Content-addressed blocks** — 以 SHA-256 hash 为主键，天然去重跨用户、跨文件。
3. **Optimistic concurrency (base_version)** — 无锁，冲突时双版本保留由用户选择。
4. **Long-polling notifications** — `asyncio.Event` 即时唤醒 + DB `delivered` 字段支持离线拉取。
5. **Resumable via session state** — 服务端维护已收块集合，客户端随时查询并续传缺失块。
6. **Quota per user** — 只计 new_unique_bytes（去重后实际新增存储），不重复计费共享块。
7. **GC for ref_count=0** — 模拟真实系统的后台空间回收。
8. **Namespace = user scope** — `ns_{user_id}`，呼应书中 namespace 设计。

## Out of Scope (by design)

- 真实分布式分片/一致性哈希
- Amazon S3 或跨区复制
- 压缩/加密管线（仅 hash 校验保证完整性）
- Web 前端 UI
- rsync 风格的字节级 delta（本实现为整块级 delta）
- 主从数据库故障转移

## Tech Stack

Python 3.11 · FastAPI · aiosqlite · Pydantic v2 · hashlib (SHA-256) · pytest + pytest-asyncio

## Spec & Plan

- Design spec: [`docs/superpowers/specs/2026-09-20-google-drive-design.md`](../docs/superpowers/specs/2026-09-20-google-drive-design.md)
- Implementation plan: [`docs/superpowers/plans/2026-09-20-google-drive.md`](../docs/superpowers/plans/2026-09-20-google-drive.md)
