# Chat System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete, runnable real-time chat system with one-on-one chat, group chat, online presence, message sync, and push notifications.

**Architecture:** Microservices with 4 backend services (API Server, Chat Server, Presence Server, Notification Server) communicating via Redis Pub/Sub, a Vue 3 frontend, PostgreSQL for metadata, and Redis for message KV storage and real-time messaging.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, SQLAlchemy (async), Redis, PostgreSQL, Vue 3, Vite, Pinia, Docker Compose

---

## File Structure

```
chat-system/
├── api-server/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app, CORS, router registration
│   │   ├── config.py            # Settings via pydantic-settings
│   │   ├── database.py          # Async SQLAlchemy engine + session
│   │   ├── models.py            # SQLAlchemy ORM models
│   │   ├── schemas.py           # Pydantic request/response schemas
│   │   ├── dependencies.py      # Auth dependency (JWT token validation)
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── auth.py          # POST /register, /login
│   │       ├── users.py         # GET/PUT /me, GET /search
│   │       ├── friends.py       # Friend request/accept/remove/list
│   │       ├── groups.py        # Group CRUD + members
│   │       └── channels.py      # GET /channels/{id}/messages
│   ├── requirements.txt
│   └── Dockerfile
├── chat-server/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app with WebSocket endpoint
│   │   ├── config.py            # Settings
│   │   ├── snowflake.py         # Snowflake ID generator
│   │   ├── connection_manager.py # WebSocket connection registry
│   │   └── message_handler.py   # Message processing logic
│   ├── requirements.txt
│   └── Dockerfile
├── presence-server/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app with heartbeat endpoint
│   │   ├── config.py            # Settings
│   │   └── heartbeat.py         # Background heartbeat checker
│   ├── requirements.txt
│   └── Dockerfile
├── notification-server/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app
│   │   ├── config.py            # Settings
│   │   └── notifier.py          # Redis subscriber for offline notifications
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue
│   │   ├── router/index.js
│   │   ├── stores/auth.js
│   │   ├── stores/chat.js
│   │   ├── composables/useWebSocket.js
│   │   ├── composables/useAuth.js
│   │   ├── views/Login.vue
│   │   ├── views/Chat.vue
│   │   ├── views/Profile.vue
│   │   ├── components/ChatSidebar.vue
│   │   ├── components/ChatWindow.vue
│   │   ├── components/MessageBubble.vue
│   │   ├── components/GroupPanel.vue
│   │   └── components/OnlineIndicator.vue
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

---

### Task 1: Project Scaffolding & Docker Infrastructure

**Files:**
- Create: `chat-system/docker-compose.yml`
- Create: `chat-system/api-server/Dockerfile`
- Create: `chat-system/api-server/requirements.txt`
- Create: `chat-system/chat-server/Dockerfile`
- Create: `chat-system/chat-server/requirements.txt`
- Create: `chat-system/presence-server/Dockerfile`
- Create: `chat-system/presence-server/requirements.txt`
- Create: `chat-system/notification-server/Dockerfile`
- Create: `chat-system/notification-server/requirements.txt`

- [ ] **Step 1: Create project root directory**

```bash
mkdir -p chat-system/api-server/app/routers
mkdir -p chat-system/chat-server/app
mkdir -p chat-system/presence-server/app
mkdir -p chat-system/notification-server/app
mkdir -p chat-system/frontend
```

- [ ] **Step 2: Create docker-compose.yml**

```yaml
# chat-system/docker-compose.yml
version: "3.9"

services:
  postgres:
    image: postgres:15
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: chat_system
      POSTGRES_USER: chat_user
      POSTGRES_PASSWORD: chat_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chat_user -d chat_system"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  api-server:
    build: ./api-server
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://chat_user:chat_password@postgres:5432/chat_system
      REDIS_URL: redis://redis:6379
      SECRET_KEY: change-me-in-production-use-openssl-rand-hex-32
    volumes:
      - ./api-server:/app

  chat-server:
    build: ./chat-server
    ports:
      - "8001:8001"
    depends_on:
      redis:
        condition: service_healthy
    environment:
      REDIS_URL: redis://redis:6379
      DATABASE_URL: postgresql+asyncpg://chat_user:chat_password@postgres:5432/chat_system
      SERVICE_NAME: chat-server-1
    volumes:
      - ./chat-server:/app

  presence-server:
    build: ./presence-server
    ports:
      - "8002:8002"
    depends_on:
      redis:
        condition: service_healthy
    environment:
      REDIS_URL: redis://redis:6379
    volumes:
      - ./presence-server:/app

  notification-server:
    build: ./notification-server
    ports:
      - "8003:8003"
    depends_on:
      redis:
        condition: service_healthy
    environment:
      REDIS_URL: redis://redis:6379
    volumes:
      - ./notification-server:/app

  frontend:
    build: ./frontend
    ports:
      - "8080:80"
    depends_on:
      - api-server
      - chat-server

volumes:
  postgres_data:
```

- [ ] **Step 3: Create API Server Dockerfile and requirements**

```dockerfile
# chat-system/api-server/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

```txt
# chat-system/api-server/requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy[asyncio]==2.0.35
asyncpg==0.29.0
redis==5.1.1
pydantic==2.9.2
pydantic-settings==2.5.2
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.12
```

- [ ] **Step 4: Create Chat Server Dockerfile and requirements**

```dockerfile
# chat-system/chat-server/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
```

```txt
# chat-system/chat-server/requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.30.6
redis==5.1.1
pydantic==2.9.2
pydantic-settings==2.5.2
sqlalchemy[asyncio]==2.0.35
asyncpg==0.29.0
```

- [ ] **Step 5: Create Presence Server Dockerfile and requirements**

```dockerfile
# chat-system/presence-server/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
```

```txt
# chat-system/presence-server/requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.30.6
redis==5.1.1
pydantic==2.9.2
pydantic-settings==2.5.2
```

- [ ] **Step 6: Create Notification Server Dockerfile and requirements**

```dockerfile
# chat-system/notification-server/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--reload"]
```

```txt
# chat-system/notification-server/requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.30.6
redis==5.1.1
pydantic==2.9.2
pydantic-settings==2.5.2
```

- [ ] **Step 7: Create __init__.py files**

Create empty `__init__.py` in each `app/` and `app/routers/` directory:
- `chat-system/api-server/app/__init__.py`
- `chat-system/api-server/app/routers/__init__.py`
- `chat-system/chat-server/app/__init__.py`
- `chat-system/presence-server/app/__init__.py`
- `chat-system/notification-server/app/__init__.py`

- [ ] **Step 8: Commit**

```bash
cd chat-system
git init
git add -A
git commit -m "chore: scaffold chat-system project with Docker infrastructure"
```

---

### Task 2: API Server — Config, Database, Models

**Files:**
- Create: `chat-system/api-server/app/config.py`
- Create: `chat-system/api-server/app/database.py`
- Create: `chat-system/api-server/app/models.py`

- [ ] **Step 1: Create config.py**

```python
# chat-system/api-server/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://chat_user:chat_password@localhost:5432/chat_system"
    REDIS_URL: str = "redis://localhost:6379"
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Create database.py**

```python
# chat-system/api-server/app/database.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 3: Create models.py**

```python
# chat-system/api-server/app/models.py
import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    group_memberships: Mapped[list["GroupMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    max_members: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list["GroupMember"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped["Group"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="group_memberships")


class Friendship(Base):
    __tablename__ = "friendships"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    friend_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Commit**

```bash
git add chat-system/api-server/app/config.py chat-system/api-server/app/database.py chat-system/api-server/app/models.py
git commit -m "feat(api-server): add config, database, and ORM models"
```

---

### Task 3: API Server — Schemas & Auth

**Files:**
- Create: `chat-system/api-server/app/schemas.py`
- Create: `chat-system/api-server/app/dependencies.py`

- [ ] **Step 1: Create schemas.py**

```python
# chat-system/api-server/app/schemas.py
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# --- Auth ---
class UserRegister(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    password: str = Field(..., min_length=6)
    nickname: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- User ---
class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    nickname: str | None
    avatar_url: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    nickname: str | None = None
    avatar_url: str | None = None


class UserSearchResult(BaseModel):
    id: uuid.UUID
    username: str
    nickname: str | None
    avatar_url: str | None


# --- Friend ---
class FriendRequest(BaseModel):
    friend_username: str


class FriendResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    nickname: str | None
    avatar_url: str | None
    status: str
    online_status: str = "offline"


# --- Group ---
class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    creator_id: uuid.UUID
    max_members: int
    created_at: datetime
    member_count: int = 0

    class Config:
        from_attributes = True


class GroupMemberAdd(BaseModel):
    user_id: uuid.UUID


class GroupMemberResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    nickname: str | None
    role: str


# --- Message ---
class MessageResponse(BaseModel):
    message_id: str
    sender_id: str
    receiver_id: str
    content: str
    type: str = "text"
    timestamp: int
    channel_type: str
```

- [ ] **Step 2: Create dependencies.py**

```python
# chat-system/api-server/app/dependencies.py
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/api-server/app/schemas.py chat-system/api-server/app/dependencies.py
git commit -m "feat(api-server): add Pydantic schemas and JWT auth dependency"
```

---

### Task 4: API Server — Auth Router

**Files:**
- Create: `chat-system/api-server/app/routers/auth.py`

- [ ] **Step 1: Create auth router**

```python
# chat-system/api-server/app/routers/auth.py
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import UserRegister, UserLogin, TokenResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    # Check if username exists
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    # Check if email exists
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        id=uuid.uuid4(),
        username=data.username,
        email=data.email,
        password=pwd_context.hash(data.password),
        nickname=data.nickname or data.username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(data.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)
```

- [ ] **Step 2: Commit**

```bash
git add chat-system/api-server/app/routers/auth.py
git commit -m "feat(api-server): add auth router with register and login"
```

---

### Task 5: API Server — Users Router

**Files:**
- Create: `chat-system/api-server/app/routers/users.py`

- [ ] **Step 1: Create users router**

```python
# chat-system/api-server/app/routers/users.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import UserResponse, UserUpdate, UserSearchResult

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if data.nickname is not None:
        current_user.nickname = data.nickname
    if data.avatar_url is not None:
        current_user.avatar_url = data.avatar_url
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("/search", response_model=list[UserSearchResult])
async def search_users(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pattern = f"%{q}%"
    result = await db.execute(
        select(User)
        .where(or_(User.username.ilike(pattern), User.nickname.ilike(pattern)))
        .where(User.id != current_user.id)
        .limit(20)
    )
    users = result.scalars().all()
    return [
        UserSearchResult(
            id=u.id, username=u.username, nickname=u.nickname, avatar_url=u.avatar_url
        )
        for u in users
    ]
```

- [ ] **Step 2: Commit**

```bash
git add chat-system/api-server/app/routers/users.py
git commit -m "feat(api-server): add users router with profile and search"
```

---

### Task 6: API Server — Friends Router

**Files:**
- Create: `chat-system/api-server/app/routers/friends.py`

- [ ] **Step 1: Create friends router**

```python
# chat-system/api-server/app/routers/friends.py
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Friendship
from app.schemas import FriendRequest, FriendResponse

router = APIRouter(prefix="/api/friends", tags=["friends"])


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.post("/request")
async def send_friend_request(
    data: FriendRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Find target user
    result = await db.execute(select(User).where(User.username == data.friend_username))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot add yourself as friend")

    # Check existing friendship (both directions)
    result = await db.execute(
        select(Friendship).where(
            or_(
                (Friendship.user_id == current_user.id) & (Friendship.friend_id == target.id),
                (Friendship.user_id == target.id) & (Friendship.friend_id == current_user.id),
            )
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Friendship already exists")

    friendship = Friendship(user_id=current_user.id, friend_id=target.id, status="pending")
    db.add(friendship)
    await db.commit()
    return {"message": "Friend request sent"}


@router.put("/{friend_id}/accept")
async def accept_friend_request(
    friend_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import uuid
    fid = uuid.UUID(friend_id)

    result = await db.execute(
        select(Friendship).where(
            Friendship.user_id == fid,
            Friendship.friend_id == current_user.id,
            Friendship.status == "pending",
        )
    )
    friendship = result.scalar_one_or_none()
    if not friendship:
        raise HTTPException(status_code=404, detail="Friend request not found")

    friendship.status = "accepted"

    # Add reverse direction for easy querying
    reverse = Friendship(user_id=current_user.id, friend_id=fid, status="accepted")
    db.add(reverse)
    await db.commit()
    return {"message": "Friend request accepted"}


@router.delete("/{friend_id}")
async def remove_friend(
    friend_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import uuid
    fid = uuid.UUID(friend_id)

    # Delete both directions
    await db.execute(
        select(Friendship).where(
            or_(
                (Friendship.user_id == current_user.id) & (Friendship.friend_id == fid),
                (Friendship.user_id == fid) & (Friendship.friend_id == current_user.id),
            )
        )
    )
    # Use delete
    from sqlalchemy import delete
    await db.execute(
        delete(Friendship).where(
            or_(
                (Friendship.user_id == current_user.id) & (Friendship.friend_id == fid),
                (Friendship.user_id == fid) & (Friendship.friend_id == current_user.id),
            )
        )
    )
    await db.commit()
    return {"message": "Friend removed"}


@router.get("", response_model=list[FriendResponse])
async def list_friends(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await get_redis()

    # Get all accepted friendships for current user
    result = await db.execute(
        select(Friendship).where(
            Friendship.user_id == current_user.id,
            Friendship.status == "accepted",
        )
    )
    friendships = result.scalars().all()
    friend_ids = [f.friend_id for f in friendships]

    if not friend_ids:
        await r.aclose()
        return []

    # Fetch friend user details
    result = await db.execute(select(User).where(User.id.in_(friend_ids)))
    friends = result.scalars().all()

    responses = []
    for friend in friends:
        # Check online status from Redis
        presence = await r.hgetall(f"presence:{friend.id}")
        online_status = presence.get("status", "offline") if presence else "offline"
        responses.append(
            FriendResponse(
                user_id=friend.id,
                username=friend.username,
                nickname=friend.nickname,
                avatar_url=friend.avatar_url,
                status="accepted",
                online_status=online_status,
            )
        )

    await r.aclose()
    return responses
```

- [ ] **Step 2: Commit**

```bash
git add chat-system/api-server/app/routers/friends.py
git commit -m "feat(api-server): add friends router with request/accept/remove/list"
```

---

### Task 7: API Server — Groups & Channels Routers

**Files:**
- Create: `chat-system/api-server/app/routers/groups.py`
- Create: `chat-system/api-server/app/routers/channels.py`

- [ ] **Step 1: Create groups router**

```python
# chat-system/api-server/app/routers/groups.py
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, Group, GroupMember
from app.schemas import (
    GroupCreate, GroupResponse, GroupMemberAdd, GroupMemberResponse, MessageResponse,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    data: GroupCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = Group(
        id=uuid.uuid4(),
        name=data.name,
        description=data.description,
        creator_id=current_user.id,
    )
    db.add(group)
    await db.flush()

    # Add creator as admin member
    member = GroupMember(group_id=group.id, user_id=current_user.id, role="admin")
    db.add(member)
    await db.commit()
    await db.refresh(group)

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        creator_id=group.creator_id,
        max_members=group.max_members,
        created_at=group.created_at,
        member_count=1,
    )


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gid = uuid.UUID(group_id)
    result = await db.execute(select(Group).where(Group.id == gid))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Count members
    count_result = await db.execute(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == gid)
    )
    member_count = count_result.scalar()

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        creator_id=group.creator_id,
        max_members=group.max_members,
        created_at=group.created_at,
        member_count=member_count,
    )


@router.post("/{group_id}/members")
async def add_member(
    group_id: str,
    data: GroupMemberAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gid = uuid.UUID(group_id)

    # Check if current user is admin
    result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == gid,
            GroupMember.user_id == current_user.id,
            GroupMember.role == "admin",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Only admins can add members")

    # Check member count
    count_result = await db.execute(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == gid)
    )
    if count_result.scalar() >= 100:
        raise HTTPException(status_code=400, detail="Group is full (max 100)")

    # Check if already member
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == data.user_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User is already a member")

    member = GroupMember(group_id=gid, user_id=data.user_id, role="member")
    db.add(member)
    await db.commit()
    return {"message": "Member added"}


@router.delete("/{group_id}/members/{user_id}")
async def remove_member(
    group_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gid = uuid.UUID(group_id)
    uid = uuid.UUID(user_id)

    # Check if current user is admin or removing self
    is_admin = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == gid,
            GroupMember.user_id == current_user.id,
            GroupMember.role == "admin",
        )
    )
    if not is_admin.scalar_one_or_none() and current_user.id != uid:
        raise HTTPException(status_code=403, detail="Only admins can remove other members")

    await db.execute(
        delete(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == uid)
    )
    await db.commit()
    return {"message": "Member removed"}


@router.get("/{group_id}/members", response_model=list[GroupMemberResponse])
async def list_members(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gid = uuid.UUID(group_id)
    result = await db.execute(
        select(User, GroupMember.role)
        .join(GroupMember, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == gid)
    )
    rows = result.all()
    return [
        GroupMemberResponse(user_id=user.id, username=user.username, nickname=user.nickname, role=role)
        for user, role in rows
    ]


@router.get("/{group_id}/messages", response_model=list[MessageResponse])
async def get_group_messages(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    before: str | None = None,
):
    gid = uuid.UUID(group_id)

    # Verify membership
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this group")

    r = await get_redis()
    inbox_key = f"inbox:{current_user.id}:{group_id}"

    if before:
        message_ids = await r.zrangebyscore(inbox_key, "-inf", float(before) - 1, start=0, num=limit, desc=True)
    else:
        message_ids = await r.zrevrange(inbox_key, 0, limit - 1)

    messages = []
    for mid in reversed(message_ids):
        msg_data = await r.get(f"message:{mid}")
        if msg_data:
            import json
            messages.append(MessageResponse(**json.loads(msg_data)))

    await r.aclose()
    return messages
```

- [ ] **Step 2: Create channels router**

```python
# chat-system/api-server/app/routers/channels.py
import json

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.schemas import MessageResponse

router = APIRouter(prefix="/api/channels", tags=["channels"])


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


@router.get("/{user_id}/messages", response_model=list[MessageResponse])
async def get_channel_messages(
    user_id: str,
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    before: str | None = None,
):
    r = await get_redis()

    # For 1-on-1 chat, the channel_id is the sorted of the two user IDs
    channel_id = "_".join(sorted([str(current_user.id), user_id]))
    inbox_key = f"inbox:{current_user.id}:{channel_id}"

    if before:
        message_ids = await r.zrangebyscore(inbox_key, "-inf", float(before) - 1, start=0, num=limit, desc=True)
    else:
        message_ids = await r.zrevrange(inbox_key, 0, limit - 1)

    messages = []
    for mid in reversed(message_ids):
        msg_data = await r.get(f"message:{mid}")
        if msg_data:
            messages.append(MessageResponse(**json.loads(msg_data)))

    await r.aclose()
    return messages
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/api-server/app/routers/groups.py chat-system/api-server/app/routers/channels.py
git commit -m "feat(api-server): add groups and channels routers"
```

---

### Task 8: API Server — Main App & Startup

**Files:**
- Create: `chat-system/api-server/app/main.py`

- [ ] **Step 1: Create main.py**

```python
# chat-system/api-server/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers import auth, users, friends, groups, channels


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Chat System API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(friends.router)
app.include_router(groups.router)
app.include_router(channels.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 2: Verify API server starts**

```bash
cd chat-system/api-server
# Start postgres and redis first: docker compose up postgres redis -d
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# Visit http://localhost:8000/docs to see Swagger UI
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/api-server/app/main.py
git commit -m "feat(api-server): add main app with CORS and router registration"
```

---

### Task 9: Chat Server — Config & Snowflake ID Generator

**Files:**
- Create: `chat-system/chat-server/app/config.py`
- Create: `chat-system/chat-server/app/snowflake.py`

- [ ] **Step 1: Create config.py**

```python
# chat-system/chat-server/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379"
    DATABASE_URL: str = "postgresql+asyncpg://chat_user:chat_password@localhost:5432/chat_system"
    SERVICE_NAME: str = "chat-server-1"
    NODE_ID: int = 1  # 0-1023 for Snowflake

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Create snowflake.py**

```python
# chat-system/chat-server/app/snowflake.py
import time
import threading


class SnowflakeGenerator:
    """
    64-bit Snowflake ID generator.
    Bit layout: 1 (sign) | 41 (timestamp) | 10 (node_id) | 12 (sequence)
    """

    EPOCH = 1700000000000  # Custom epoch: 2023-11-14

    def __init__(self, node_id: int = 1):
        if node_id < 0 or node_id > 1023:
            raise ValueError("node_id must be between 0 and 1023")
        self.node_id = node_id
        self.sequence = 0
        self.last_timestamp = -1
        self.lock = threading.Lock()

    def _current_millis(self) -> int:
        return int(time.time() * 1000)

    def generate(self) -> int:
        with self.lock:
            timestamp = self._current_millis()

            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & 0xFFF
                if self.sequence == 0:
                    # Sequence exhausted, wait for next millisecond
                    while timestamp <= self.last_timestamp:
                        timestamp = self._current_millis()
            else:
                self.sequence = 0

            if timestamp < self.last_timestamp:
                raise RuntimeError(f"Clock moved backwards. Refusing to generate ID for {self.last_timestamp - timestamp}ms")

            self.last_timestamp = timestamp
            msg_id = ((timestamp - self.EPOCH) << 22) | (self.node_id << 12) | self.sequence
            return msg_id


# Singleton instance
generator = SnowflakeGenerator(node_id=1)
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/chat-server/app/config.py chat-system/chat-server/app/snowflake.py
git commit -m "feat(chat-server): add config and Snowflake ID generator"
```

---

### Task 10: Chat Server — Connection Manager & Message Handler

**Files:**
- Create: `chat-system/chat-server/app/connection_manager.py`
- Create: `chat-system/chat-server/app/message_handler.py`

- [ ] **Step 1: Create connection_manager.py**

```python
# chat-system/chat-server/app/connection_manager.py
import json
from typing import Dict

from fastapi import WebSocket
import redis.asyncio as redis

from app.config import settings


class ConnectionManager:
    """Manages WebSocket connections and Redis Pub/Sub subscriptions."""

    def __init__(self):
        # user_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        self.redis: redis.Redis | None = None
        self.pubsub: redis.client.PubSub | None = None

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

        # Register in Redis
        r = await self._get_redis()
        await r.set(f"user_server:{user_id}", settings.SERVICE_NAME)
        await r.hset(f"presence:{user_id}", mapping={
            "status": "online",
            "last_heartbeat": str(int(__import__("time").time())),
        })

        # Subscribe to personal channel
        await self.pubsub.subscribe(f"channel:{user_id}")

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)

    async def cleanup(self, user_id: str):
        r = await self._get_redis()
        await r.delete(f"user_server:{user_id}")
        await r.hset(f"presence:{user_id}", mapping={"status": "offline"})
        await self.pubsub.unsubscribe(f"channel:{user_id}")

    async def send_personal(self, user_id: str, data: dict):
        ws = self.active_connections.get(user_id)
        if ws:
            await ws.send_json(data)

    async def broadcast_to_group(self, group_id: str, user_ids: list[str], data: dict):
        for uid in user_ids:
            await self.send_personal(uid, data)

    async def listen_pubsub(self):
        """Listen for messages from Redis Pub/Sub and forward to WebSocket clients."""
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    data = json.loads(message["data"])

                    # Route message to the right user(s)
                    if channel.startswith("channel:group:"):
                        group_id = channel.split("channel:group:")[1]
                        # Forward to all connected users in this group
                        # The data should contain target_user_ids
                        target_ids = data.pop("target_user_ids", [])
                        for uid in target_ids:
                            await self.send_personal(uid, data)
                    elif channel.startswith("channel:"):
                        user_id = channel.split("channel:")[1]
                        await self.send_personal(user_id, data)
        except Exception:
            pass  # Connection closed

    async def _get_redis(self) -> redis.Redis:
        if self.redis is None:
            self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self.pubsub = self.redis.pubsub()
        return self.redis


manager = ConnectionManager()
```

- [ ] **Step 2: Create message_handler.py**

```python
# chat-system/chat-server/app/message_handler.py
import json
import time

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.snowflake import generator

# Database setup for chat server
engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


async def handle_send_message(sender_id: str, receiver_id: str, content: str, channel_type: str):
    """Process an outgoing message."""
    r = await get_redis()
    msg_id = str(generator.generate())
    timestamp = int(time.time())

    message = {
        "message_id": msg_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "content": content,
        "type": "text",
        "timestamp": timestamp,
        "channel_type": channel_type,
    }

    # Store message in KV store
    await r.set(f"message:{msg_id}", json.dumps(message))

    if channel_type == "one_to_one":
        await _handle_one_to_one(r, sender_id, receiver_id, message)
    elif channel_type == "group":
        await _handle_group_message(r, sender_id, receiver_id, message)

    await r.aclose()
    return message


async def _handle_one_to_one(r: redis.Redis, sender_id: str, receiver_id: str, message: dict):
    """Handle one-to-one message delivery."""
    channel_id = "_".join(sorted([sender_id, receiver_id]))

    # Add to sender's inbox
    await r.zadd(f"inbox:{sender_id}:{channel_id}", {message["message_id"]: int(message["message_id"])})

    # Add to receiver's inbox
    await r.zadd(f"inbox:{receiver_id}:{channel_id}", {message["message_id"]: int(message["message_id"])})

    # Check if receiver is online
    presence = await r.hgetall(f"presence:{receiver_id}")
    if presence and presence.get("status") == "online":
        # Publish to receiver's channel
        await r.publish(f"channel:{receiver_id}", json.dumps({
            "type": "new_message",
            "message": message,
        }))
    else:
        # Queue offline notification
        await r.publish("notification:offline", json.dumps({
            "user_id": receiver_id,
            "message": message,
        }))


async def _handle_group_message(r: redis.Redis, sender_id: str, group_id: str, message: dict):
    """Handle group message with fanout-on-write."""
    # Get all group members from database
    async with async_session() as db:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT user_id FROM group_members WHERE group_id = :gid"),
            {"gid": group_id},
        )
        member_ids = [str(row[0]) for row in result.fetchall()]

    # Fanout: add to each member's inbox
    target_user_ids = []
    for member_id in member_ids:
        await r.zadd(f"inbox:{member_id}:{group_id}", {message["message_id"]: int(message["message_id"])})
        if member_id != sender_id:
            # Check if member is online
            presence = await r.hgetall(f"presence:{member_id}")
            if presence and presence.get("status") == "online":
                target_user_ids.append(member_id)
            else:
                await r.publish("notification:offline", json.dumps({
                    "user_id": member_id,
                    "message": message,
                }))

    # Broadcast to online members via Pub/Sub
    if target_user_ids:
        payload = {
            "type": "new_message",
            "message": message,
            "target_user_ids": target_user_ids,
        }
        await r.publish(f"channel:group:{group_id}", json.dumps(payload))


async def handle_sync(user_id: str, channel_id: str, last_message_id: str):
    """Sync messages for a user since last_message_id."""
    r = await get_redis()
    inbox_key = f"inbox:{user_id}:{channel_id}"

    # Get all message IDs greater than last_message_id
    message_ids = await r.zrangebyscore(
        inbox_key,
        float(last_message_id) + 1 if last_message_id != "0" else "-inf",
        "+inf",
    )

    messages = []
    for mid in message_ids:
        msg_data = await r.get(f"message:{mid}")
        if msg_data:
            messages.append(json.loads(msg_data))

    await r.aclose()
    return messages
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/chat-server/app/connection_manager.py chat-system/chat-server/app/message_handler.py
git commit -m "feat(chat-server): add connection manager and message handler"
```

---

### Task 11: Chat Server — WebSocket Endpoint & Main App

**Files:**
- Create: `chat-system/chat-server/app/main.py`

- [ ] **Step 1: Create main.py**

```python
# chat-system/chat-server/app/main.py
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio

from app.connection_manager import manager
from app.message_handler import handle_send_message, handle_sync


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start Pub/Sub listener
    task = asyncio.create_task(manager.listen_pubsub())
    yield
    task.cancel()


app = FastAPI(title="Chat Server", lifespan=lifespan)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """
    WebSocket endpoint. Client connects with ws://host:8001/ws?token=<jwt_token>
    The token contains the user_id in its payload.
    For simplicity, we decode without verification here.
    In production, verify the JWT against the API server's secret.
    """
    # Decode JWT to get user_id (simplified - in production verify signature)
    try:
        from jose import jwt
        payload = jwt.decode(token, "change-me-in-production-use-openssl-rand-hex-32", algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token")
            return
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(user_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "send_message":
                message = await handle_send_message(
                    sender_id=user_id,
                    receiver_id=data["receiver_id"],
                    content=data["content"],
                    channel_type=data.get("channel_type", "one_to_one"),
                )
                # Also send back to sender for confirmation
                await manager.send_personal(user_id, {
                    "type": "new_message",
                    "message": message,
                })

            elif msg_type == "sync":
                messages = await handle_sync(
                    user_id=user_id,
                    channel_id=data["channel_id"],
                    last_message_id=data.get("last_message_id", "0"),
                )
                await manager.send_personal(user_id, {
                    "type": "message_sync",
                    "messages": messages,
                })

            elif msg_type == "typing":
                # Broadcast typing indicator
                channel_id = data.get("channel_id")
                if channel_id:
                    await manager.send_personal(channel_id, {
                        "type": "typing",
                        "user_id": user_id,
                    })

    except WebSocketDisconnect:
        manager.disconnect(user_id)
        await manager.cleanup(user_id)
    except Exception:
        manager.disconnect(user_id)
        await manager.cleanup(user_id)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "chat-server"}
```

- [ ] **Step 2: Add jose to chat-server requirements**

Append to `chat-system/chat-server/requirements.txt`:
```
python-jose[cryptography]==3.3.0
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/chat-server/app/main.py chat-system/chat-server/requirements.txt
git commit -m "feat(chat-server): add WebSocket endpoint and main app"
```

---

### Task 12: Presence Server

**Files:**
- Create: `chat-system/presence-server/app/config.py`
- Create: `chat-system/presence-server/app/heartbeat.py`
- Create: `chat-system/presence-server/app/main.py`

- [ ] **Step 1: Create config.py**

```python
# chat-system/presence-server/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379"
    HEARTBEAT_INTERVAL: int = 10  # seconds
    OFFLINE_THRESHOLD: int = 30   # seconds
    SCAN_INTERVAL: int = 30       # seconds

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Create heartbeat.py**

```python
# chat-system/presence-server/app/heartbeat.py
import json
import time
import asyncio

import redis.asyncio as redis

from app.config import settings


class HeartbeatChecker:
    """Background task that checks for offline users."""

    def __init__(self):
        self.redis: redis.Redis | None = None
        self._running = False

    async def start(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._running = True
        asyncio.create_task(self._scan_loop())

    async def stop(self):
        self._running = False
        if self.redis:
            await self.redis.aclose()

    async def update_heartbeat(self, user_id: str):
        """Update heartbeat timestamp for a user."""
        await self.redis.hset(f"presence:{user_id}", mapping={
            "status": "online",
            "last_heartbeat": str(int(time.time())),
        })

    async def _scan_loop(self):
        """Periodically scan for users who haven't sent heartbeats."""
        while self._running:
            try:
                await asyncio.sleep(settings.SCAN_INTERVAL)
                await self._check_offline_users()
            except Exception:
                await asyncio.sleep(5)

    async def _check_offline_users(self):
        """Find users whose heartbeat is older than threshold and mark them offline."""
        now = int(time.time())
        cursor = 0
        offline_users = []

        while True:
            cursor, keys = await self.redis.scan(cursor, match="presence:*", count=100)
            for key in keys:
                data = await self.redis.hgetall(key)
                if data and data.get("status") == "online":
                    last_hb = int(data.get("last_heartbeat", 0))
                    if now - last_hb > settings.OFFLINE_THRESHOLD:
                        user_id = key.replace("presence:", "")
                        offline_users.append(user_id)

            if cursor == 0:
                break

        for user_id in offline_users:
            await self.redis.hset(f"presence:{user_id}", "status", "offline")
            # Broadcast offline status
            await self.redis.publish(
                f"channel:presence:{user_id}",
                json.dumps({"user_id": user_id, "status": "offline"}),
            )


heartbeat_checker = HeartbeatChecker()
```

- [ ] **Step 3: Create main.py**

```python
# chat-system/presence-server/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException

from app.heartbeat import heartbeat_checker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await heartbeat_checker.start()
    yield
    await heartbeat_checker.stop()


app = FastAPI(title="Presence Server", lifespan=lifespan)


@app.post("/heartbeat")
async def receive_heartbeat(user_id: str = Header(...)):
    """Receive heartbeat from a client."""
    await heartbeat_checker.update_heartbeat(user_id)
    return {"status": "ok"}


@app.get("/presence/{user_id}")
async def get_presence(user_id: str):
    """Get online status of a user."""
    r = heartbeat_checker.redis
    data = await r.hgetall(f"presence:{user_id}")
    if not data:
        return {"user_id": user_id, "status": "offline"}
    return {"user_id": user_id, "status": data.get("status", "offline")}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "presence-server"}
```

- [ ] **Step 4: Commit**

```bash
git add chat-system/presence-server/
git commit -m "feat(presence-server): add heartbeat checker and presence API"
```

---

### Task 13: Notification Server

**Files:**
- Create: `chat-system/notification-server/app/config.py`
- Create: `chat-system/notification-server/app/notifier.py`
- Create: `chat-system/notification-server/app/main.py`

- [ ] **Step 1: Create config.py**

```python
# chat-system/notification-server/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379"

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Create notifier.py**

```python
# chat-system/notification-server/app/notifier.py
import json
import asyncio

import redis.asyncio as redis

from app.config import settings


class NotificationService:
    """Subscribes to Redis offline notification channel and logs/processes notifications."""

    def __init__(self):
        self.redis: redis.Redis | None = None
        self.pubsub: redis.client.PubSub | None = None
        self._running = False
        self.notifications: list[dict] = []  # In-memory log for demo

    async def start(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        await self.pubsub.subscribe("notification:offline")
        self._running = True
        asyncio.create_task(self._listen())

    async def stop(self):
        self._running = False
        if self.pubsub:
            await self.pubsub.unsubscribe("notification:offline")
            await self.pubsub.aclose()
        if self.redis:
            await self.redis.aclose()

    async def _listen(self):
        """Listen for offline notifications."""
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    self.notifications.append(data)
                    # In production: send push notification via APNs/FCM
                    print(f"[NOTIFICATION] User {data['user_id']} has offline message from {data['message']['sender_id']}")
        except Exception:
            pass


notification_service = NotificationService()
```

- [ ] **Step 3: Create main.py**

```python
# chat-system/notification-server/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.notifier import notification_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    await notification_service.start()
    yield
    await notification_service.stop()


app = FastAPI(title="Notification Server", lifespan=lifespan)


@app.get("/notifications")
async def get_notifications():
    """Get recent offline notifications (for debugging/demo)."""
    return notification_service.notifications


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notification-server"}
```

- [ ] **Step 4: Commit**

```bash
git add chat-system/notification-server/
git commit -m "feat(notification-server): add offline notification subscriber"
```

---

### Task 14: Vue Frontend — Project Setup

**Files:**
- Create: `chat-system/frontend/package.json`
- Create: `chat-system/frontend/vite.config.js`
- Create: `chat-system/frontend/index.html`
- Create: `chat-system/frontend/src/main.js`
- Create: `chat-system/frontend/src/App.vue`
- Create: `chat-system/frontend/src/router/index.js`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "chat-system-frontend",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.2.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: Create vite.config.js**

```javascript
// chat-system/frontend/vite.config.js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 8080,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8001',
        ws: true,
      },
    },
  },
})
```

- [ ] **Step 3: Create index.html**

```html
<!-- chat-system/frontend/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Chat System</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create main.js**

```javascript
// chat-system/frontend/src/main.js
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
```

- [ ] **Step 5: Create App.vue**

```vue
<!-- chat-system/frontend/src/App.vue -->
<template>
  <router-view />
</template>

<script setup>
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: #f0f2f5;
  height: 100vh;
}

#app {
  height: 100vh;
}
</style>
```

- [ ] **Step 6: Create router/index.js**

```javascript
// chat-system/frontend/src/router/index.js
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
  },
  {
    path: '/',
    name: 'Chat',
    component: () => import('../views/Chat.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('../views/Profile.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  if (to.meta.requiresAuth && !authStore.isLoggedIn) {
    next('/login')
  } else if (to.name === 'Login' && authStore.isLoggedIn) {
    next('/')
  } else {
    next()
  }
})

export default router
```

- [ ] **Step 7: Install dependencies and verify**

```bash
cd chat-system/frontend
npm install
npm run dev
```

- [ ] **Step 8: Commit**

```bash
git add chat-system/frontend/
git commit -m "feat(frontend): scaffold Vue 3 project with router and Pinia"
```

---

### Task 15: Vue Frontend — Auth Store & Composable

**Files:**
- Create: `chat-system/frontend/src/stores/auth.js`
- Create: `chat-system/frontend/src/composables/useAuth.js`

- [ ] **Step 1: Create auth store**

```javascript
// chat-system/frontend/src/stores/auth.js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

const API_BASE = '/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)

  function setToken(newToken) {
    token.value = newToken
    localStorage.setItem('token', newToken)
    axios.defaults.headers.common['Authorization'] = `Bearer ${newToken}`
  }

  function clearToken() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    delete axios.defaults.headers.common['Authorization']
  }

  async function login(username, password) {
    const res = await axios.post(`${API_BASE}/auth/login`, { username, password })
    setToken(res.data.access_token)
    await fetchProfile()
  }

  async function register(username, email, password, nickname) {
    await axios.post(`${API_BASE}/auth/register`, { username, email, password, nickname })
    await login(username, password)
  }

  async function fetchProfile() {
    try {
      const res = await axios.get(`${API_BASE}/users/me`)
      user.value = res.data
    } catch {
      clearToken()
    }
  }

  function logout() {
    clearToken()
  }

  // Initialize axios default header if token exists
  if (token.value) {
    axios.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
  }

  return { token, user, isLoggedIn, login, register, fetchProfile, logout, clearToken }
})
```

- [ ] **Step 2: Create useAuth composable**

```javascript
// chat-system/frontend/src/composables/useAuth.js
import { useAuthStore } from '../stores/auth'

export function useAuth() {
  const authStore = useAuthStore()

  return {
    login: authStore.login,
    register: authStore.register,
    logout: authStore.logout,
    user: authStore.user,
    isLoggedIn: authStore.isLoggedIn,
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/frontend/src/stores/auth.js chat-system/frontend/src/composables/useAuth.js
git commit -m "feat(frontend): add auth store and composable"
```

---

### Task 16: Vue Frontend — Chat Store & WebSocket Composable

**Files:**
- Create: `chat-system/frontend/src/stores/chat.js`
- Create: `chat-system/frontend/src/composables/useWebSocket.js`

- [ ] **Step 1: Create chat store**

```javascript
// chat-system/frontend/src/stores/chat.js
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

const API_BASE = '/api'

export const useChatStore = defineStore('chat', () => {
  const friends = ref([])
  const groups = ref([])
  const conversations = ref({})  // channelId -> messages[]
  const activeChannel = ref(null) // { type: 'one_to_one'|'group', id: string, name: string }
  const onlineStatuses = ref({}) // userId -> 'online'|'offline'

  async function fetchFriends() {
    const res = await axios.get(`${API_BASE}/friends`)
    friends.value = res.data
    res.data.forEach(f => {
      onlineStatuses.value[f.user_id] = f.online_status
    })
  }

  async function fetchGroups() {
    // Fetch user's groups (list all groups user is member of)
    // For simplicity, we'll use a dedicated endpoint or derive from created groups
    // Here we fetch groups the user created or is member of
    try {
      const res = await axios.get(`${API_BASE}/groups/my-groups`)
      groups.value = res.data
    } catch {
      groups.value = []
    }
  }

  async function loadMessages(channelId, channelType) {
    let url
    if (channelType === 'one_to_one') {
      url = `${API_BASE}/channels/${channelId}/messages`
    } else {
      url = `${API_BASE}/groups/${channelId}/messages`
    }
    const res = await axios.get(url)
    conversations.value[channelId] = res.data
  }

  function addMessage(channelId, message) {
    if (!conversations.value[channelId]) {
      conversations.value[channelId] = []
    }
    conversations.value[channelId].push(message)
  }

  function setActiveChannel(type, id, name) {
    activeChannel.value = { type, id, name }
  }

  function updateOnlineStatus(userId, status) {
    onlineStatuses.value[userId] = status
  }

  return {
    friends, groups, conversations, activeChannel, onlineStatuses,
    fetchFriends, fetchGroups, loadMessages, addMessage,
    setActiveChannel, updateOnlineStatus,
  }
})
```

- [ ] **Step 2: Create useWebSocket composable**

```javascript
// chat-system/frontend/src/composables/useWebSocket.js
import { ref, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'

const WS_URL = 'ws://localhost:8001/ws'

export function useWebSocket(token) {
  const chatStore = useChatStore()
  const ws = ref(null)
  const isConnected = ref(false)
  const reconnectAttempts = ref(0)
  const maxReconnectAttempts = 10

  function connect() {
    const url = `${WS_URL}?token=${token}`
    ws.value = new WebSocket(url)

    ws.value.onopen = () => {
      isConnected.value = true
      reconnectAttempts.value = 0
      console.log('WebSocket connected')
    }

    ws.value.onmessage = (event) => {
      const data = JSON.parse(event.data)

      if (data.type === 'new_message') {
        const msg = data.message
        const channelId = msg.channel_type === 'group'
          ? msg.receiver_id
          : msg.sender_id === getCurrentUserId() ? msg.receiver_id : msg.sender_id
        chatStore.addMessage(channelId, msg)
      } else if (data.type === 'message_sync') {
        data.messages.forEach(msg => {
          const channelId = msg.channel_type === 'group'
            ? msg.receiver_id
            : msg.sender_id === getCurrentUserId() ? msg.receiver_id : msg.sender_id
          chatStore.addMessage(channelId, msg)
        })
      } else if (data.type === 'presence_update') {
        chatStore.updateOnlineStatus(data.user_id, data.status)
      } else if (data.type === 'error') {
        console.error('WebSocket error:', data.message)
      }
    }

    ws.value.onclose = () => {
      isConnected.value = false
      attemptReconnect()
    }

    ws.value.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }

  function attemptReconnect() {
    if (reconnectAttempts.value < maxReconnectAttempts) {
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.value), 30000)
      reconnectAttempts.value++
      console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts.value})`)
      setTimeout(connect, delay)
    }
  }

  function send(data) {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify(data))
    }
  }

  function sendMessage(receiverId, content, channelType = 'one_to_one') {
    send({
      type: 'send_message',
      receiver_id: receiverId,
      content: content,
      channel_type: channelType,
    })
  }

  function syncMessages(channelId, lastMessageId) {
    send({
      type: 'sync',
      channel_id: channelId,
      last_message_id: lastMessageId,
    })
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
  }

  function getCurrentUserId() {
    // Decode from JWT token (simplified)
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      return payload.sub
    } catch {
      return null
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect, disconnect, send, sendMessage, syncMessages,
    isConnected, ws,
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/frontend/src/stores/chat.js chat-system/frontend/src/composables/useWebSocket.js
git commit -m "feat(frontend): add chat store and WebSocket composable"
```

---

### Task 17: Vue Frontend — Login View

**Files:**
- Create: `chat-system/frontend/src/views/Login.vue`

- [ ] **Step 1: Create Login.vue**

```vue
<!-- chat-system/frontend/src/views/Login.vue -->
<template>
  <div class="login-container">
    <div class="login-card">
      <h1>Chat System</h1>
      <p class="subtitle">Real-time messaging</p>

      <div class="tabs">
        <button :class="{ active: mode === 'login' }" @click="mode = 'login'">Login</button>
        <button :class="{ active: mode === 'register' }" @click="mode = 'register'">Register</button>
      </div>

      <form @submit.prevent="handleSubmit">
        <div class="form-group">
          <input v-model="username" type="text" placeholder="Username" required />
        </div>

        <div v-if="mode === 'register'" class="form-group">
          <input v-model="email" type="email" placeholder="Email" required />
        </div>

        <div v-if="mode === 'register'" class="form-group">
          <input v-model="nickname" type="text" placeholder="Nickname (optional)" />
        </div>

        <div class="form-group">
          <input v-model="password" type="password" placeholder="Password" required />
        </div>

        <p v-if="error" class="error">{{ error }}</p>

        <button type="submit" class="submit-btn" :disabled="loading">
          {{ loading ? 'Loading...' : (mode === 'login' ? 'Login' : 'Register') }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const mode = ref('login')
const username = ref('')
const email = ref('')
const password = ref('')
const nickname = ref('')
const error = ref('')
const loading = ref(false)

async function handleSubmit() {
  error.value = ''
  loading.value = true
  try {
    if (mode.value === 'login') {
      await authStore.login(username.value, password.value)
    } else {
      await authStore.register(username.value, email.value, password.value, nickname.value)
    }
    router.push('/')
  } catch (e) {
    error.value = e.response?.data?.detail || 'An error occurred'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  background: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  width: 400px;
  text-align: center;
}

h1 {
  color: #333;
  margin-bottom: 0.5rem;
}

.subtitle {
  color: #666;
  margin-bottom: 1.5rem;
}

.tabs {
  display: flex;
  margin-bottom: 1.5rem;
  border-bottom: 2px solid #eee;
}

.tabs button {
  flex: 1;
  padding: 0.75rem;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 1rem;
  color: #999;
  transition: all 0.3s;
}

.tabs button.active {
  color: #667eea;
  border-bottom: 2px solid #667eea;
  margin-bottom: -2px;
}

.form-group {
  margin-bottom: 1rem;
}

.form-group input {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 1rem;
  outline: none;
  transition: border-color 0.3s;
}

.form-group input:focus {
  border-color: #667eea;
}

.error {
  color: #e74c3c;
  font-size: 0.9rem;
  margin-bottom: 1rem;
}

.submit-btn {
  width: 100%;
  padding: 0.75rem;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  cursor: pointer;
  transition: opacity 0.3s;
}

.submit-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.submit-btn:hover:not(:disabled) {
  opacity: 0.9;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add chat-system/frontend/src/views/Login.vue
git commit -m "feat(frontend): add Login view"
```

---

### Task 18: Vue Frontend — Chat Components

**Files:**
- Create: `chat-system/frontend/src/components/OnlineIndicator.vue`
- Create: `chat-system/frontend/src/components/MessageBubble.vue`
- Create: `chat-system/frontend/src/components/ChatSidebar.vue`
- Create: `chat-system/frontend/src/components/ChatWindow.vue`
- Create: `chat-system/frontend/src/components/GroupPanel.vue`

- [ ] **Step 1: Create OnlineIndicator.vue**

```vue
<!-- chat-system/frontend/src/components/OnlineIndicator.vue -->
<template>
  <span class="indicator" :class="status"></span>
</template>

<script setup>
defineProps({
  status: { type: String, default: 'offline' }
})
</script>

<style scoped>
.indicator {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
}
.indicator.online { background-color: #2ecc71; }
.indicator.offline { background-color: #bdc3c7; }
</style>
```

- [ ] **Step 2: Create MessageBubble.vue**

```vue
<!-- chat-system/frontend/src/components/MessageBubble.vue -->
<template>
  <div class="message-bubble" :class="{ own: isOwn }">
    <div class="sender" v-if="!isOwn">{{ senderName }}</div>
    <div class="bubble">
      <p>{{ message.content }}</p>
      <span class="time">{{ formatTime(message.timestamp) }}</span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  message: { type: Object, required: true },
  isOwn: { type: Boolean, default: false },
  senderName: { type: String, default: '' },
})

function formatTime(timestamp) {
  return new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.message-bubble {
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
  max-width: 70%;
}

.message-bubble.own {
  margin-left: auto;
  align-items: flex-end;
}

.sender {
  font-size: 0.75rem;
  color: #666;
  margin-bottom: 2px;
  padding-left: 12px;
}

.bubble {
  padding: 10px 14px;
  border-radius: 18px;
  background: #e9ecef;
  color: #333;
  position: relative;
}

.own .bubble {
  background: #667eea;
  color: white;
}

.bubble p {
  margin: 0;
  word-wrap: break-word;
  line-height: 1.4;
}

.time {
  font-size: 0.7rem;
  opacity: 0.7;
  display: block;
  text-align: right;
  margin-top: 4px;
}
</style>
```

- [ ] **Step 3: Create ChatSidebar.vue**

```vue
<!-- chat-system/frontend/src/components/ChatSidebar.vue -->
<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <h2>Chats</h2>
      <button @click="$emit('showGroups')" class="icon-btn" title="Groups">👥</button>
    </div>

    <div class="search-box">
      <input v-model="searchQuery" placeholder="Search users..." @input="searchUsers" />
    </div>

    <!-- Search Results -->
    <div v-if="searchResults.length" class="section">
      <h3>Search Results</h3>
      <div v-for="user in searchResults" :key="user.id" class="contact"
           @click="$emit('startChat', user)">
        <OnlineIndicator :status="onlineStatuses[user.id] || 'offline'" />
        <span>{{ user.nickname || user.username }}</span>
      </div>
    </div>

    <!-- Friends List -->
    <div class="section">
      <h3>Friends</h3>
      <div v-for="friend in friends" :key="friend.user_id" class="contact"
           :class="{ active: activeChannel?.id === friend.user_id }"
           @click="$emit('selectFriend', friend)">
        <OnlineIndicator :status="friend.online_status" />
        <span>{{ friend.nickname || friend.username }}</span>
      </div>
      <p v-if="!friends.length" class="empty">No friends yet. Search for users above.</p>
    </div>

    <!-- Groups List -->
    <div class="section">
      <h3>Groups</h3>
      <div v-for="group in groups" :key="group.id" class="contact"
           :class="{ active: activeChannel?.id === group.id }"
           @click="$emit('selectGroup', group)">
        <span>👥 {{ group.name }}</span>
        <span class="badge">{{ group.member_count }}</span>
      </div>
      <p v-if="!groups.length" class="empty">No groups yet.</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'
import OnlineIndicator from './OnlineIndicator.vue'

const props = defineProps({
  friends: Array,
  groups: Array,
  onlineStatuses: Object,
  activeChannel: Object,
})

defineEmits(['selectFriend', 'selectGroup', 'startChat', 'showGroups'])

const searchQuery = ref('')
const searchResults = ref([])

async function searchUsers() {
  if (searchQuery.value.length < 1) {
    searchResults.value = []
    return
  }
  try {
    const res = await axios.get(`/api/users/search?q=${searchQuery.value}`)
    searchResults.value = res.data
  } catch {
    searchResults.value = []
  }
}
</script>

<style scoped>
.sidebar {
  width: 300px;
  background: white;
  border-right: 1px solid #e0e0e0;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid #eee;
}

.sidebar-header h2 { font-size: 1.2rem; color: #333; }

.icon-btn {
  background: none;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
}

.search-box {
  padding: 0.5rem 1rem;
}

.search-box input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 20px;
  outline: none;
  font-size: 0.9rem;
}

.section {
  padding: 0.5rem 0;
}

.section h3 {
  padding: 0.25rem 1rem;
  font-size: 0.8rem;
  color: #999;
  text-transform: uppercase;
}

.contact {
  display: flex;
  align-items: center;
  padding: 0.75rem 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.contact:hover, .contact.active {
  background: #f0f2f5;
}

.empty {
  padding: 0.5rem 1rem;
  color: #999;
  font-size: 0.85rem;
}

.badge {
  margin-left: auto;
  background: #667eea;
  color: white;
  border-radius: 10px;
  padding: 2px 8px;
  font-size: 0.75rem;
}
</style>
```

- [ ] **Step 4: Create ChatWindow.vue**

```vue
<!-- chat-system/frontend/src/components/ChatWindow.vue -->
<template>
  <div class="chat-window">
    <div class="chat-header" v-if="channel">
      <h3>{{ channel.name }}</h3>
      <OnlineIndicator v-if="channel.type === 'one_to_one'" :status="peerStatus" />
    </div>
    <div class="chat-header" v-else>
      <h3>Select a conversation</h3>
    </div>

    <div class="messages" ref="messagesContainer">
      <MessageBubble
        v-for="msg in messages"
        :key="msg.message_id"
        :message="msg"
        :is-own="msg.sender_id === currentUserId"
        :sender-name="getSenderName(msg.sender_id)"
      />
      <p v-if="!messages.length && channel" class="empty-chat">No messages yet. Say hello!</p>
    </div>

    <div class="input-area" v-if="channel">
      <input
        v-model="newMessage"
        placeholder="Type a message..."
        @keyup.enter="sendMsg"
        @keyup="sendTyping"
      />
      <button @click="sendMsg" :disabled="!newMessage.trim()">Send</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import MessageBubble from './MessageBubble.vue'
import OnlineIndicator from './OnlineIndicator.vue'

const props = defineProps({
  channel: Object,
  messages: Array,
  currentUserId: String,
  peerStatus: { type: String, default: 'offline' },
})

const emit = defineEmits(['send', 'typing'])

const newMessage = ref('')
const messagesContainer = ref(null)

function sendMsg() {
  if (!newMessage.value.trim()) return
  emit('send', newMessage.value.trim())
  newMessage.value = ''
}

function sendTyping() {
  emit('typing')
}

function getSenderName(senderId) {
  return senderId === props.currentUserId ? 'You' : senderId.substring(0, 8)
}

watch(() => props.messages?.length, () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
})
</script>

<style scoped>
.chat-window {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f8f9fa;
}

.chat-header {
  padding: 1rem;
  background: white;
  border-bottom: 1px solid #eee;
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-header h3 { font-size: 1.1rem; color: #333; }

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.empty-chat {
  text-align: center;
  color: #999;
  margin-top: 2rem;
}

.input-area {
  display: flex;
  padding: 1rem;
  background: white;
  border-top: 1px solid #eee;
  gap: 0.5rem;
}

.input-area input {
  flex: 1;
  padding: 0.75rem 1rem;
  border: 1px solid #ddd;
  border-radius: 24px;
  outline: none;
  font-size: 0.95rem;
}

.input-area input:focus {
  border-color: #667eea;
}

.input-area button {
  padding: 0.75rem 1.5rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 24px;
  cursor: pointer;
  font-size: 0.95rem;
}

.input-area button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
```

- [ ] **Step 5: Create GroupPanel.vue**

```vue
<!-- chat-system/frontend/src/components/GroupPanel.vue -->
<template>
  <div class="group-panel" v-if="visible">
    <div class="panel-header">
      <h3>Groups</h3>
      <button @click="$emit('close')" class="close-btn">&times;</button>
    </div>

    <!-- Create Group -->
    <div class="section">
      <h4>Create Group</h4>
      <input v-model="newGroupName" placeholder="Group name" />
      <input v-model="newGroupDesc" placeholder="Description (optional)" />
      <button @click="createGroup" :disabled="!newGroupName.trim()">Create</button>
    </div>

    <!-- My Groups -->
    <div class="section">
      <h4>My Groups</h4>
      <div v-for="group in groups" :key="group.id" class="group-item">
        <div>
          <strong>{{ group.name }}</strong>
          <p>{{ group.member_count }} members</p>
        </div>
        <button @click="$emit('selectGroup', group)">Open</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'

const props = defineProps({
  visible: Boolean,
  groups: Array,
})

const emit = defineEmits(['close', 'selectGroup', 'groupCreated'])

const newGroupName = ref('')
const newGroupDesc = ref('')

async function createGroup() {
  if (!newGroupName.value.trim()) return
  try {
    await axios.post('/api/groups', {
      name: newGroupName.value,
      description: newGroupDesc.value || null,
    })
    newGroupName.value = ''
    newGroupDesc.value = ''
    emit('groupCreated')
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to create group')
  }
}
</script>

<style scoped>
.group-panel {
  position: fixed;
  right: 0;
  top: 0;
  width: 350px;
  height: 100vh;
  background: white;
  box-shadow: -4px 0 20px rgba(0,0,0,0.1);
  z-index: 100;
  overflow-y: auto;
  padding: 1rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #666;
}

.section {
  margin-bottom: 1.5rem;
}

.section h4 {
  color: #333;
  margin-bottom: 0.5rem;
}

.section input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 6px;
  margin-bottom: 0.5rem;
  outline: none;
}

.section button {
  width: 100%;
  padding: 0.5rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.section button:disabled {
  opacity: 0.5;
}

.group-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem;
  border: 1px solid #eee;
  border-radius: 8px;
  margin-bottom: 0.5rem;
}

.group-item button {
  width: auto;
  padding: 0.25rem 0.75rem;
}
</style>
```

- [ ] **Step 6: Commit**

```bash
git add chat-system/frontend/src/components/
git commit -m "feat(frontend): add chat UI components"
```

---

### Task 19: Vue Frontend — Chat & Profile Views

**Files:**
- Create: `chat-system/frontend/src/views/Chat.vue`
- Create: `chat-system/frontend/src/views/Profile.vue`

- [ ] **Step 1: Create Chat.vue**

```vue
<!-- chat-system/frontend/src/views/Chat.vue -->
<template>
  <div class="chat-layout">
    <ChatSidebar
      :friends="chatStore.friends"
      :groups="chatStore.groups"
      :online-statuses="chatStore.onlineStatuses"
      :active-channel="chatStore.activeChannel"
      @select-friend="selectFriend"
      @select-group="selectGroup"
      @start-chat="startChat"
      @show-groups="showGroupPanel = true"
    />

    <ChatWindow
      :channel="chatStore.activeChannel"
      :messages="currentMessages"
      :current-user-id="currentUserId"
      :peer-status="peerStatus"
      @send="sendMessage"
      @typing="sendTyping"
    />

    <GroupPanel
      :visible="showGroupPanel"
      :groups="chatStore.groups"
      @close="showGroupPanel = false"
      @select-group="selectGroup"
      @group-created="refreshGroups"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'
import { useWebSocket } from '../composables/useWebSocket'
import ChatSidebar from '../components/ChatSidebar.vue'
import ChatWindow from '../components/ChatWindow.vue'
import GroupPanel from '../components/GroupPanel.vue'

const authStore = useAuthStore()
const chatStore = useChatStore()
const showGroupPanel = ref(false)

const currentUserId = computed(() => authStore.user?.id || '')
const currentMessages = computed(() => {
  if (!chatStore.activeChannel) return []
  const id = chatStore.activeChannel.type === 'one_to_one'
    ? getChannelId(chatStore.activeChannel.id)
    : chatStore.activeChannel.id
  return chatStore.conversations[id] || []
})

const peerStatus = computed(() => {
  if (chatStore.activeChannel?.type === 'one_to_one') {
    return chatStore.onlineStatuses[chatStore.activeChannel.id] || 'offline'
  }
  return 'offline'
})

// WebSocket setup
const ws = useWebSocket(authStore.token)

function getChannelId(otherUserId) {
  const ids = [currentUserId.value, otherUserId].sort()
  return ids.join('_')
}

function selectFriend(friend) {
  const channelId = getChannelId(friend.user_id)
  chatStore.setActiveChannel('one_to_one', friend.user_id, friend.nickname || friend.username)
  chatStore.loadMessages(channelId, 'one_to_one')
}

function selectGroup(group) {
  chatStore.setActiveChannel('group', group.id, group.name)
  chatStore.loadMessages(group.id, 'group')
  showGroupPanel.value = false
}

function startChat(user) {
  selectFriend({ user_id: user.id, nickname: user.nickname, username: user.username, online_status: 'offline' })
}

function sendMessage(content) {
  if (!chatStore.activeChannel) return
  const receiverId = chatStore.activeChannel.type === 'one_to_one'
    ? chatStore.activeChannel.id
    : chatStore.activeChannel.id
  const channelType = chatStore.activeChannel.type
  ws.sendMessage(receiverId, content, channelType)
}

function sendTyping() {
  // Could send typing indicator
}

async function refreshGroups() {
  await chatStore.fetchGroups()
}

onMounted(async () => {
  await authStore.fetchProfile()
  ws.connect()
  await chatStore.fetchFriends()
  await chatStore.fetchGroups()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  background: #f0f2f5;
}
</style>
```

- [ ] **Step 2: Create Profile.vue**

```vue
<!-- chat-system/frontend/src/views/Profile.vue -->
<template>
  <div class="profile-container">
    <div class="profile-card">
      <button @click="$router.push('/')" class="back-btn">← Back to Chat</button>
      <h2>Profile</h2>

      <div class="avatar">
        <div class="avatar-circle">{{ initials }}</div>
      </div>

      <form @submit.prevent="updateProfile">
        <div class="form-group">
          <label>Username</label>
          <input :value="authStore.user?.username" disabled />
        </div>
        <div class="form-group">
          <label>Email</label>
          <input :value="authStore.user?.email" disabled />
        </div>
        <div class="form-group">
          <label>Nickname</label>
          <input v-model="nickname" placeholder="Your nickname" />
        </div>

        <button type="submit" class="save-btn">Save Changes</button>
      </form>

      <button @click="handleLogout" class="logout-btn">Logout</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import axios from 'axios'

const router = useRouter()
const authStore = useAuthStore()
const nickname = ref('')

const initials = computed(() => {
  const name = authStore.user?.nickname || authStore.user?.username || '?'
  return name.charAt(0).toUpperCase()
})

async function updateProfile() {
  try {
    await axios.put('/api/users/me', { nickname: nickname.value })
    await authStore.fetchProfile()
    alert('Profile updated!')
  } catch (e) {
    alert('Failed to update profile')
  }
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

onMounted(() => {
  nickname.value = authStore.user?.nickname || ''
})
</script>

<style scoped>
.profile-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: #f0f2f5;
}

.profile-card {
  background: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.1);
  width: 400px;
  text-align: center;
}

.back-btn {
  background: none;
  border: none;
  color: #667eea;
  cursor: pointer;
  font-size: 0.9rem;
  margin-bottom: 1rem;
}

.avatar-circle {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  margin: 1rem auto;
}

.form-group {
  margin-bottom: 1rem;
  text-align: left;
}

.form-group label {
  display: block;
  font-size: 0.85rem;
  color: #666;
  margin-bottom: 0.25rem;
}

.form-group input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 6px;
  outline: none;
}

.form-group input:disabled {
  background: #f5f5f5;
  color: #999;
}

.save-btn {
  width: 100%;
  padding: 0.75rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  margin-top: 0.5rem;
}

.logout-btn {
  width: 100%;
  padding: 0.75rem;
  background: #e74c3c;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  margin-top: 1rem;
}
</style>
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/frontend/src/views/
git commit -m "feat(frontend): add Chat and Profile views"
```

---

### Task 20: Frontend Docker & Nginx Config

**Files:**
- Create: `chat-system/frontend/nginx.conf`
- Create: `chat-system/frontend/Dockerfile`

- [ ] **Step 1: Create nginx.conf**

```nginx
# chat-system/frontend/nginx.conf
server {
    listen 80;
    server_name localhost;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://api-server:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws {
        proxy_pass http://chat-server:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
# chat-system/frontend/Dockerfile
FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/frontend/nginx.conf chat-system/frontend/Dockerfile
git commit -m "feat(frontend): add Docker and Nginx configuration"
```

---

### Task 21: README & Final Integration

**Files:**
- Create: `chat-system/README.md`

- [ ] **Step 1: Create README.md**

```markdown
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
docker compose up --build

# Access the frontend
open http://localhost:8080

# API docs
open http://localhost:8000/docs
```

## Development

### Backend
```bash
cd api-server
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```
```

- [ ] **Step 2: Final commit**

```bash
git add chat-system/README.md
git commit -m "docs: add README with quick start guide"
```

- [ ] **Step 3: Build and test**

```bash
cd chat-system
docker compose up --build
# Visit http://localhost:8080
```
