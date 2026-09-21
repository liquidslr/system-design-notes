"""Auth: register, login, token verification."""
import hashlib
import secrets
import time

from fastapi import HTTPException, Request

from .config import DriveConfig
from .database import Database

# In-memory token->user_id map (session store); use Redis in production.
_tokens: dict[str, str] = {}


async def register(db: Database, email: str, password: str) -> str:
    """Create user; return user_id."""
    if await db.get_user_by_email(email):
        raise HTTPException(409, "Email already registered")
    user_id = f"u_{secrets.token_hex(8)}"
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.insert_user(user_id, email, pwd_hash, salt, DriveConfig().default_quota_bytes, now)
    return user_id


async def login(db: Database, email: str, password: str) -> str | None:
    """Validate credentials; return session token or None."""
    user = await db.get_user_by_email(email)
    if not user:
        return None
    pwd_hash = hashlib.sha256((password + user["salt"]).encode()).hexdigest()
    if pwd_hash != user["pwd_hash"]:
        return None
    token = secrets.token_hex(32)
    _tokens[token] = user["user_id"]
    return token


def get_current_user(request: Request) -> str:
    """FastAPI dependency: extract Bearer token -> user_id."""
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    uid = _tokens.get(token)
    if not uid:
        raise HTTPException(401, "Unauthorized")
    return uid
