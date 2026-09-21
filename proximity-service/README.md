# Proximity Service — Geohash & Quadtree Location Search

基于 [Chapter 16: Design Proximity Service](../16.%20Proximity%20Service/Readme.md) 系统设计文档的可运行实现。
实现两种地理索引算法（Geohash 半径搜索 + Quadtree k-NN），交叉验证并对比延迟。

## Features

| 设计概念 | 实现方式 |
|---------|---------|
| Geohash 编码 | `geohash.encode()` 经度位优先交织 + base32 |
| Geohash 邻居（边界问题） | `geohash.neighbors()` 中心格 + 8 邻居并集，decode→偏移→重编码 |
| 精度选择 | `precision_for_radius()` 按章节半径-精度表选格子大小 |
| Haversine 距离 | `geo.haversine_m()` 单一距离来源；`bounding_box()` 包围盒 |
| Quadtree 空间索引 | `quadtree.Quadtree` 容量分裂 + best-first k-NN（bbox 剪枝）+ 半径查询 |
| 两级 LRU 缓存 | `cache.CacheLayer`：geohash→[ids] 与 id→详情 两层，命中/未命中计数 |
| 读写路径分离 | `BusinessService`（写/维护索引）与 `LBSService`（读/检索）职责拆分 |
| 启动构建 + 增量维护 | `rebuild_indexes()` 启动加载；create/update/delete 增量改索引 |
| 双算法对比 | `/v1/compare` 用 `perf_counter` 计时返回两算法结果与延迟 |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  FastAPI Server (server.py) — lifespan 装配 & 启动构建索引     │
│  ┌───────────────────────────┐  ┌──────────────────────────┐  │
│  │  LBSService (读路径)       │  │  BusinessService (写路径) │  │
│  │  search_nearby (geohash)   │  │  create/update/delete     │  │
│  │  search_knn    (quadtree)  │  │  rebuild_indexes          │  │
│  └────────────┬──────────────┘  └────────────┬─────────────┘  │
│               │        共享 SpatialIndex       │                │
│       ┌───────▼────────┐            ┌─────────▼──────────┐    │
│       │ geohash_index  │            │  Quadtree          │    │
│       │ {cell→ids}     │            │  (kNN / radius)    │    │
│       └────────────────┘            └────────────────────┘    │
│  ┌────────────────┐   ┌──────────────────────────────────┐   │
│  │ CacheLayer     │   │ Database (SQLite / aiosqlite)     │   │
│  │ (两级 LRU)      │   │ businesses 表                    │   │
│  └────────────────┘   └──────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install dependencies

```powershell
cd proximity-service
pip install -r requirements.txt
```

### 2. Run Demo (no server needed)

```powershell
python __main__.py --demo
```

故事线：seed 30 家旧金山商家 → 3km 半径搜索 → k-NN=5 → 边界问题邻居救援 → 双算法延迟对比 → 缓存命中率统计。

### 3. Run API Server

```powershell
python __main__.py --server
# Server starts on http://0.0.0.0:9300
```

### 4. Use CLI Client

```powershell
python cli.py add "Blue Bottle" 37.7720 -122.4140 --category cafe
python cli.py nearby 37.7848 -122.4055 3000
python cli.py knn 37.7848 -122.4055 5
python cli.py compare 37.7848 -122.4055 3000 10
python cli.py get 1
python cli.py delete 1
python cli.py stats
```

### 5. Run Tests

```powershell
python -m pytest tests/ -v
```

21 个测试覆盖：geo/geohash/quadtree 单元 + 读写路径端到端检索（半径/kNN/双算法一致/缓存/坐标迁移/删除）。

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/businesses` | 新增商家（写路径维护索引） |
| GET | `/v1/businesses/{id}` | 查询商家详情 |
| PUT | `/v1/businesses/{id}` | 更新商家（坐标变化则迁移索引） |
| DELETE | `/v1/businesses/{id}` | 删除商家 |
| GET | `/v1/search/nearby?lat&lng&radius` | Geohash 半径搜索（中心 + 8 邻居） |
| GET | `/v1/search/knn?lat&lng&k` | Quadtree k-最近邻搜索 |
| GET | `/v1/compare?lat&lng&radius&k` | 两算法结果 + 延迟对比 |
| GET | `/v1/stats` | 商家/网格/quadtree 点数/缓存命中统计 |

## Design Decisions

1. **两算法并存 + 交叉验证** — Geohash 擅长半径过滤与分布式分片；Quadtree 擅长精确 k-NN。二者结果一致性由测试保证。
2. **邻居并集解决边界问题** — 查询点靠近格边时，邻近商家可能落在相邻格，单中心格会漏检；`center + 8 neighbors` 救援。
3. **Quadtree 无删除** — 章节指出删除代价高；删除/坐标迁移采用标记 + kNN 读时按 `_coords` 过滤 stale 条目，批量重建兜底。
4. **两级缓存映射章节 Redis** — geohash→ids 与 id→details 分离，读放大可控，命中率可观测。
5. **读写服务分离** — LBS（读重、无状态逻辑）与 Business（写、独占索引维护）拆分，模拟线上独立扩缩容。
6. **纯逻辑模块可独立单测** — geo/geohash/quadtree 无 I/O，与 DB/服务层解耦。

## Out of Scope (by design)

- Google S2 Geometry（章节第 3 种算法，仅注释说明，未实现）
- 真实分布式分片 / 一致性哈希路由 LBS worker
- Redis / 跨进程共享缓存（以进程内 LRU 模拟）
- 增量 GeoHash 精度自适应（固定 `default_precision`）
- Web 前端 UI 与地图渲染

## Tech Stack

Python 3.11 · FastAPI · uvicorn · aiosqlite · Pydantic v2 · stdlib heapq/math · pytest + pytest-asyncio

## Spec & Plan

- Design spec: [`docs/superpowers/specs/2026-09-20-proximity-service-design.md`](../docs/superpowers/specs/2026-09-20-proximity-service-design.md)
- Implementation plan: [`docs/superpowers/plans/2026-09-20-proximity-service.md`](../docs/superpowers/plans/2026-09-20-proximity-service.md)
