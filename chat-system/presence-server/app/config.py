from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379"
    HEARTBEAT_INTERVAL: int = 10  # seconds
    OFFLINE_THRESHOLD: int = 30   # seconds
    SCAN_INTERVAL: int = 30       # seconds

    class Config:
        env_file = ".env"


settings = Settings()
