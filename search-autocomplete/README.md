# Search Autocomplete System

基于《System Design Interview》第 13 章设计实现的搜索自动补全系统。

## 功能特性

- **Trie 前缀树**: 带 top-k 缓存的高效数据结构，O(1) 前缀查询
- **自底向上缓存重建**: 后续序遍历重建所有节点的 top-k 建议
- **后台数据聚合**: 定期聚合用户搜索日志，更新频率并重建 Trie
- **建议过滤器**: 内存黑名单机制，实时过滤不当内容
- **种子数据**: 内置 70+ 热门查询演示数据
- **REST API**: FastAPI 提供完整管理接口
- **Web 前端**: Vue 3 搜索框 UI，300ms 防抖、键盘导航、频率可视化

## 架构

```
User Input ──→ Frontend (Vue 3) ──→ API Server ──→ Query Service ──→ Trie (top-k cache)
                                      │                                    │
                                 SQLite DB                            Suggestion Filter
                                      │
                               Aggregator Worker
                               (periodic rebuild)
```

| 组件 | 文件 | 职责 |
|------|------|------|
| API Server | `app/server.py` | FastAPI REST API，路由请求 |
| Query Service | `app/query_service.py` | 协调 Trie 查找与过滤 |
| Trie | `app/trie.py` | 带 top-k 缓存的前缀树数据结构 |
| Aggregator | `app/aggregator.py` | 后台 Worker，聚合日志并重建 Trie |
| Filter | `app/filter.py` | 建议过滤器，内存黑名单 |
| Database | `app/database.py` | aiosqlite 异步数据库层 |
| Config | `app/config.py` | 系统配置与种子数据 |
| Models | `app/models.py` | Pydantic 请求/响应模型 |
| Frontend | `frontend/src/` | Vue 3 + Vite 搜索界面 |

## 快速开始

### Docker 部署（推荐）

```bash
cd search-autocomplete
docker compose up --build

# 前端 UI: http://localhost:3000
# 后端 API: http://localhost:8000
# API 文档: http://localhost:8000/docs
```

### 本地开发

```bash
# 后端
pip install -r search-autocomplete/requirements.txt
python search-autocomplete/__main__.py

# 前端
cd search-autocomplete/frontend
npm install
npm run dev
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/suggestions?prefix=xxx` | 获取自动补全建议 |
| POST | `/api/queries` | 记录用户搜索查询 |
| POST | `/api/filter` | 添加过滤黑名单 |
| DELETE | `/api/filter/{query}` | 移除过滤 |
| POST | `/api/trie/rebuild` | 手动触发 Trie 重建 |
| GET | `/api/stats` | 系统统计 |

## 查询建议示例

```json
GET /api/suggestions?prefix=go

{
  "prefix": "go",
  "suggestions": [
    {"query": "google", "frequency": 2000},
    {"query": "google maps", "frequency": 900},
    {"query": "google translate", "frequency": 850},
    {"query": "google drive", "frequency": 700}
  ]
}
```

## 设计要点

1. **Trie + Top-K 缓存**: 每个节点缓存子树中频率最高的 5 个查询，前缀遍历后 O(1) 返回建议
2. **数据聚合流水线**: Analytics Logs → Aggregator → Frequencies Table → Trie Rebuild
3. **自底向上缓存重建**: 后续序遍历收集所有完整查询，按频率降序排序后设置 top-k
4. **建议过滤**: 内存黑名单集合，返回建议前过滤，支持动态添加/移除
5. **SQLite 持久化**: 三张表（query_logs, frequencies, filter_list）异步操作
6. **水平扩展**: 无状态 API Server + 共享数据库，可多实例部署

## 技术栈

- **后端:** Python 3.11, FastAPI, aiosqlite, Pydantic
- **前端:** Vue 3, Vite, Axios
- **基础设施:** Docker Compose, Nginx
