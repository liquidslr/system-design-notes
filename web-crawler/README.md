# Web Crawler

基于《System Design Interview》第 9 章设计实现的可扩展 Web 爬虫系统。

## 功能特性

- **BFS 遍历**: 广度优先搜索，避免深度过大
- **URL Frontier**: 优先级队列 + 礼貌性控制（per-domain 延迟）
- **DNS 缓存**: 线程池解析 + TTL 缓存，避免重复查询
- **HTML 下载**: 异步 aiohttp + ThreadedResolver
- **内容解析**: BeautifulSoup 解析 HTML，提取标题/文本/链接
- **URL 提取**: 相对链接转绝对链接，规范化，过滤
- **去重检测**: Content Seen (SHA-256) + URL Seen (内存 Set)
- **Spider Trap 防护**: URL 长度限制、路径参数限制
- **SQLite 存储**: 元数据持久化 + 磁盘 HTML 文件存储
- **CLI 接口**: 灵活的命令行参数

## 架构

```
Seed URLs → URL Frontier → HTML Downloader → Content Parser
                 ↑                                  ↓
                 └── URL Filter ← URL Extractor ← Content Seen?
```

| 组件 | 文件 | 职责 |
|------|------|------|
| Crawler Engine | `app/crawler.py` | BFS 遍历协调，Worker 管理 |
| URL Frontier | `app/components/url_frontier.py` | 优先级队列 + 礼貌性控制 |
| DNS Resolver | `app/components/dns_resolver.py` | DNS 解析 + TTL 缓存 |
| HTML Downloader | `app/components/html_downloader.py` | 异步页面下载 |
| Content Parser | `app/components/content_parser.py` | HTML 解析 + URL 提取 + 过滤 |
| Dedup | `app/components/dedup.py` | URL 去重 + 内容去重 |
| Storage | `app/storage/content_storage.py` | SQLite 元数据 + 磁盘 HTML |
| Config | `app/config.py` | 爬虫配置 |
| Models | `app/models.py` | 数据模型 |
| CLI | `__main__.py` | 命令行入口 |

## 快速开始

```bash
# 安装依赖
pip install -r web-crawler/requirements.txt

# 默认种子 URL 运行
python web-crawler/__main__.py --max-pages 20 --workers 3

# 自定义种子 URL
python web-crawler/__main__.py --urls https://example.com https://httpbin.org/html

# 指定种子文件
python web-crawler/__main__.py --seed-file seeds.txt --max-depth 5

# 详细日志
python web-crawler/__main__.py -v
```

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--urls` | 内置种子 | 种子 URL 列表 |
| `--seed-file` | - | 种子 URL 文件（每行一个） |
| `--max-pages` | 50 | 最大爬取页数 |
| `--workers` | 10 | 并发 Worker 数 |
| `--max-depth` | 3 | 最大爬取深度 |
| `--politeness-delay` | 1.0 | 同域名请求间隔（秒） |
| `--no-robots` | False | 禁用 robots.txt 遵守 |
| `--output-dir` | crawled_pages | 页面存储目录 |
| `--verbose` | False | 详细日志 |

## 设计要点

1. **可扩展性**: 异步架构，多 Worker 并行，支持分布式扩展
2. **礼貌性**: per-domain 延迟，避免对单一服务器造成压力
3. **健壮性**: 完善的错误处理，超时控制，异常捕获
4. **去重**: 双层去重（URL + 内容），SHA-256 哈希比较
5. **存储**: SQLite 元数据 + 磁盘文件，内存缓存热数据
