# Chat System

A real-time chat system built with Python FastAPI microservices and Vue 3 frontend.

## Features

- One-on-one real-time messaging via WebSocket
- Group chat (max 100 members)
- Online presence indicators with heartbeat
- Multi-device message synchronization
- Push notifications for offline users
- JWT authentication

## Architecture

| Service | Port | Description |
|---------|------|-------------|
| API Server | 8000 | Auth, users, groups, friends |
| Chat Server | 8001 | WebSocket messaging |
| Presence Server | 8002 | Online status heartbeat |
| Notification Server | 8003 | Offline notifications |
| Vue Frontend | 8080 | Web UI |
| PostgreSQL | 5432 | User/group metadata |
| Redis | 6379 | Message KV store + Pub/Sub |

## Quick Start

```bash
# Start all services
cd chat-system
docker compose up --build

# Access the frontend
# http://localhost:8080

# API docs
# http://localhost:8000/docs
```

## Development

### Backend (API Server)
```bash
cd chat-system/api-server
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd chat-system/frontend
npm install
npm run dev
```

## Tech Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy (async), Redis, PostgreSQL
- **Frontend:** Vue 3, Vite, Pinia, Vue Router
- **Infrastructure:** Docker Compose, Nginx
