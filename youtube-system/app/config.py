"""Configuration for the YouTube video streaming system (api-server)."""
import os
from dataclasses import dataclass


@dataclass
class Config:
    # Storage (volume-mounted at /app/data in Docker)
    db_path: str = os.getenv("DB_PATH", "data/youtube.db")
    original_dir: str = os.getenv("ORIGINAL_DIR", "data/original")
    transcoded_dir: str = os.getenv("TRANSCODED_DIR", "data/transcoded")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Redis queues (design doc: message queue decoupling)
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    task_queue: str = "transcode:tasks"
    event_queue: str = "transcode:events"

    # Upload rules (design doc assumptions: max 1GB per video)
    presign_ttl: int = 300
    max_upload_bytes: int = 1 << 30  # 1GB
    allowed_exts: tuple = ("mp4", "mov", "avi", "mkv", "webm")

    # Auth: JWT access token (stateless) + opaque refresh token (Redis)
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-in-production")
    access_token_ttl: int = int(os.getenv("ACCESS_TOKEN_TTL", "900"))       # 15min
    refresh_token_ttl: int = int(os.getenv("REFRESH_TOKEN_TTL", "604800"))  # 7d
    ban_marker_ttl: int = int(os.getenv("BAN_MARKER_TTL", "86400"))         # 1d, see spec 2.5


config = Config()
