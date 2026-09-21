# Chat System Design Specification

## Overview

A complete, runnable demo of a real-time chat system supporting one-on-one chat, group chat (max 100 users), online presence indicators, multi-device message synchronization, and push notifications. Designed for 50 million DAU scale.

## Architecture

### Microservices

| Service | Port | Responsibility |
|---------|------|----------------|
| API Server | 8000 | User auth (JWT), user CRUD, group CRUD, friend management |
| Chat Server | 8001 | WebSocket connections, message sending/receiving, message ID generation (Snowflake), message sync |
| Presence Server | 8002 | Heartbeat processing, online/offline status management, status broadcast via Pub/Sub |
| Notification Server | 8003 | Offline message push notifications via Redis subscription |
| Vue Frontend | 8080 | User interface served by Nginx |

### Infrastructure

| Component | Port | Purpose |
|-----------|------|---------|
| PostgreSQL 15 | 5432 | User metadata, group data, friendships |
| Redis 7 | 6379 | Message KV store, online presence, Pub/Sub messaging, message queues |

### Inter-Service Communication

- Services communicate via **Redis Pub/Sub**
- Chat Server subscribes to user channels for message delivery
- Presence Server publishes status changes
- Notification Server subscribes to offline notification channel

## Data Models

### PostgreSQL

```sql
users (
    id          UUID PRIMARY KEY,
    username    VARCHAR(50) UNIQUE NOT NULL,
    email       VARCHAR(100) UNIQUE NOT NULL,
    password    VARCHAR(255) NOT NULL,  -- bcrypt hashed
    nickname    VARCHAR(50),
    avatar_url  VARCHAR(500),
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
)

groups (
    id          UUID PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    description TEXT,
    creator_id  UUID REFERENCES users(id),
    max_members INT DEFAULT 100,
    created_at  TIMESTAMP DEFAULT NOW()
)

group_members (
    group_id    UUID REFERENCES groups(id),
    user_id     UUID REFERENCES users(id),
    role        VARCHAR(20) DEFAULT 'member',
    joined_at   TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (group_id, user_id)
)

friendships (
    user_id     UUID REFERENCES users(id),
    friend_id   UUID REFERENCES users(id),
    status      VARCHAR(20) DEFAULT 'pending',
    created_at  TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, friend_id)
)
```

### Redis

```
# Message storage (KV Store)
message:{message_id} → JSON {
    "message_id": "snowflake_id",
    "sender_id": "user_uuid",
    "receiver_id": "user_uuid | channel_id",
    "content": "text",
    "type": "text",
    "timestamp": unix_timestamp,
    "channel_type": "one_to_one | group"
}

# User inbox - sorted set of message IDs per channel
inbox:{user_id}:{channel_id} → Sorted Set
    score = message_id (snowflake)
    member = message_id

# Online presence
presence:{user_id} → Hash {
    "status": "online|offline|away",
    "last_heartbeat": unix_timestamp,
    "connected_at": unix_timestamp
}

# User-to-ChatServer mapping
user_server:{user_id} → chat_server_id

# Pub/Sub channels
channel:{user_id}           → personal message delivery
channel:group:{group_id}    → group message broadcast
channel:presence:{user_id}  → online status updates (fanout)
notification:offline        → offline notification queue
```

### Message ID Generation

Snowflake-like 64-bit integer:
- 41 bits: timestamp (milliseconds)
- 10 bits: server node ID
- 12 bits: sequence number
- Generated locally by Chat Server, no centralized allocation needed

## Core Flows

### 1. One-on-One Messaging

1. User A sends message via WebSocket to Chat Server 1
2. Chat Server 1 generates Snowflake message ID
3. Store message in Redis KV: `message:{id}`
4. Add message ID to User B's inbox sorted set
5. Publish to Redis Pub/Sub: `channel:{User_B}`
6. Chat Server 2 (managing User B's connection) receives the message
7. Forward to User B via WebSocket
8. If User B is offline: publish to `notification:offline` channel

### 2. Group Messaging (Fanout on Write)

1. User A sends message to group via WebSocket
2. Chat Server generates message ID, stores in Redis KV
3. Query all group members from PostgreSQL
4. Add message to each member's inbox: `inbox:{member_id}:{group_id}`
5. Publish to `channel:group:{group_id}`
6. All Chat Servers with group members subscribed receive and forward via WebSocket

### 3. Message Synchronization (Multi-Device)

1. Device reconnects, sends sync request with `last_message_id`
2. Chat Server queries inbox for messages with `message_id > last_message_id`
3. Returns batch of new messages
4. Client updates its `cur_max_message_id`

### 4. Online Presence

1. Client sends heartbeat every 10 seconds to Presence Server
2. Presence Server updates `presence:{user_id}.last_heartbeat` in Redis
3. Background task scans every 30 seconds:
   - If `now - last_heartbeat > 30s` → mark user offline
   - Publish status change to friends' presence channels
4. Friends receive real-time presence updates via Pub/Sub

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login (returns JWT)

### Users
- `GET /api/users/me` - Get current user profile
- `PUT /api/users/me` - Update profile
- `GET /api/users/search?q=` - Search users

### Friends
- `POST /api/friends/request` - Send friend request
- `PUT /api/friends/{id}/accept` - Accept friend request
- `DELETE /api/friends/{id}` - Remove friend
- `GET /api/friends` - List friends (with online status)

### Groups
- `POST /api/groups` - Create group
- `GET /api/groups/{id}` - Get group info
- `POST /api/groups/{id}/members` - Add member
- `DELETE /api/groups/{id}/members/{uid}` - Remove member
- `GET /api/groups/{id}/messages` - Get group chat history (paginated)

### Channels
- `GET /api/channels/{user_id}/messages` - Get 1-on-1 chat history (paginated)

### WebSocket (Chat Server)
```
ws://chat-server:8001/ws
→ {type: "send_message", receiver_id, content, channel_type}
→ {type: "sync", last_message_id, channel_id}
→ {type: "typing", channel_id}
← {type: "new_message", message}
← {type: "presence_update", user_id, status}
← {type: "message_sync", messages[]}
← {type: "error", code, message}
```

## Vue Frontend

### Structure
```
frontend/
├── src/
│   ├── views/
│   │   ├── Login.vue           # Login/Register page
│   │   ├── Chat.vue            # Main chat interface
│   │   └── Profile.vue         # User profile page
│   ├── components/
│   │   ├── ChatSidebar.vue     # Conversation list (friends + groups)
│   │   ├── ChatWindow.vue      # Chat window (message list + input)
│   │   ├── MessageBubble.vue   # Message bubble component
│   │   ├── GroupPanel.vue      # Group management panel
│   │   └── OnlineIndicator.vue # Online status indicator
│   ├── composables/
│   │   ├── useWebSocket.js     # WebSocket connection management
│   │   └── useAuth.js          # Authentication logic
│   ├── stores/
│   │   ├── auth.js             # Pinia auth state
│   │   └── chat.js             # Pinia chat state
│   ├── router/
│   │   └── index.js            # Vue Router
│   └── App.vue
├── package.json
└── vite.config.js
```

### Tech Stack
- Vue 3 (Composition API)
- Vite (build tool)
- Pinia (state management)
- Vue Router (routing)
- Native WebSocket API

## Project Structure

```
chat-system/
├── api-server/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── groups.py
│   │   │   └── friends.py
│   │   ├── models/
│   │   │   └── models.py
│   │   ├── schemas/
│   │   │   └── schemas.py
│   │   └── services/
│   │       └── auth_service.py
│   ├── requirements.txt
│   └── Dockerfile
├── chat-server/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── websocket.py
│   │   ├── message_handler.py
│   │   └── snowflake.py
│   ├── requirements.txt
│   └── Dockerfile
├── presence-server/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   └── heartbeat.py
│   ├── requirements.txt
│   └── Dockerfile
├── notification-server/
│   ├── app/
│   │   ├── main.py
│   │   └── config.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── (Vue 3 project)
├── docker-compose.yml
└── README.md
```

## Docker Compose

```yaml
services:
  postgres:
    image: postgres:15
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: chat_system
      POSTGRES_USER: chat_user
      POSTGRES_PASSWORD: chat_password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports: ["6379:6379"]

  api-server:
    build: ./api-server
    ports: ["8000:8000"]
    depends_on: [postgres, redis]
    environment:
      DATABASE_URL: postgresql+asyncpg://chat_user:chat_password@postgres:5432/chat_system
      REDIS_URL: redis://redis:6379

  chat-server:
    build: ./chat-server
    ports: ["8001:8001"]
    depends_on: [redis]
    environment:
      REDIS_URL: redis://redis:6379

  presence-server:
    build: ./presence-server
    ports: ["8002:8002"]
    depends_on: [redis]
    environment:
      REDIS_URL: redis://redis:6379

  notification-server:
    build: ./notification-server
    ports: ["8003:8003"]
    depends_on: [redis]
    environment:
      REDIS_URL: redis://redis:6379

  frontend:
    build: ./frontend
    ports: ["8080:80"]
    depends_on: [api-server, chat-server]

volumes:
  postgres_data:
```

## Error Handling

- **WebSocket reconnection**: Client auto-reconnects with exponential backoff
- **Message delivery retry**: Chat Server retries 3 times before queuing to notification
- **Server failure**: Service discovery via health checks; clients reconnect to available server
- **Database failures**: Connection pooling with retry logic

## Scalability Considerations

- **Horizontal scaling**: Chat Servers are stateless (connection state in Redis); add instances behind load balancer
- **Redis clustering**: For 50M DAU, use Redis Cluster for message KV store
- **Database read replicas**: PostgreSQL read replicas for user/group queries
- **CDN**: Static frontend assets served via CDN
