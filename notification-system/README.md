# Notification System

基于《System Design Interview》第 10 章设计实现的可扩展通知系统。

## 功能特性

- **多渠道通知**: 支持 iOS Push (APNS)、Android Push (FCM)、SMS、Email
- **消息队列解耦**: 异步处理，缓冲高并发通知
- **Worker 池**: 多 Worker 并行消费队列并发送通知
- **去重机制**: 基于 event_id 防止重复发送
- **限流保护**: 每用户每小时/每天通知上限
- **Opt-out 支持**: 用户可按渠道关闭通知
- **模板引擎**: Jinja2 模板，支持预定义和自定义模板
- **重试机制**: 指数退避重试，防止临时故障丢失
- **通知日志**: SQLite 持久化，支持统计和审计
- **REST API**: FastAPI 提供完整管理接口

## 架构

```
Trigger Services ──→ Notification Server ──→ Message Queue ──→ Workers ──→ Third-party Services
                          │                                                       │
                     ┌────┴────┐                                           ┌──────┼──────┐
                     │   DB    │                                          APNS  FCM  SMS/Email
                     └─────────┘
```

| 组件 | 文件 | 职责 |
|------|------|------|
| Notification Server | `app/server.py` | REST API，接收通知请求 |
| Core Service | `app/service.py` | 验证、去重、限流、模板渲染、入队 |
| Message Queue | `app/queue/message_queue.py` | 异步队列，解耦发送与处理 |
| Workers | `app/workers.py` | 消费队列，调用第三方服务，重试 |
| Providers | `app/providers/providers.py` | APNS/FCM/SMS/Email 适配器（Mock） |
| Templates | `app/templates.py` | 通知模板引擎 |
| Database | `app/database.py` | 用户、设备、设置、日志存储 |
| Config | `app/config.py` | 系统配置 |
| Models | `app/models.py` | 数据模型定义 |

## 快速开始

```bash
# 安装依赖
pip install -r notification-system/requirements.txt

# 运行 Demo
python notification-system/__main__.py --demo

# 启动 API Server
python notification-system/__main__.py --server
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/notifications/send` | 发送通知 |
| POST | `/api/users/register` | 注册用户 |
| POST | `/api/devices/register` | 注册设备 Token |
| PUT | `/api/settings` | 更新通知偏好 |
| GET | `/api/settings/{user_id}` | 查询通知偏好 |
| GET | `/api/logs` | 查询通知日志 |
| GET | `/api/stats` | 系统统计 |
| GET | `/health` | 健康检查 |

## 发送通知示例

```json
POST /api/notifications/send
{
    "user_id": "user_1",
    "event_type": "billing_reminder",
    "channel": "email",
    "template_id": "billing_reminder_email",
    "template_data": {
        "user_name": "Alice",
        "amount": "29.99",
        "due_date": "2026-10-01"
    }
}
```

## 设计要点

1. **水平扩展**: 多个 Notification Server 实例 + 消息队列解耦
2. **可靠性**: 数据库持久化 + 重试机制防止数据丢失
3. **去重**: event_id 检查避免重复通知
4. **限流**: 保护用户免受通知轰炸
5. **模板化**: 统一管理通知内容，支持多语言/多格式
6. **监控**: 队列深度监控，动态扩缩 Worker
