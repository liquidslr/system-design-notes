from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://localhost:6379"
    DATABASE_URL: str = "postgresql+asyncpg://chat_user:chat_password@localhost:5432/chat_system"
    SERVICE_NAME: str = "chat-server-1"
    NODE_ID: int = 1  # 0-1023 for Snowflake

    class Config:
        env_file = ".env"


settings = Settings()
