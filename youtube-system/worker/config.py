"""Configuration for transcoder workers."""
import os
import socket
from dataclasses import dataclass


@dataclass
class WorkerConfig:
    # Max concurrent encodes per worker instance
    concurrency: int = int(os.getenv("CONCURRENCY", "2"))

    # Health endpoint port (exposed inside the docker network, not on host,
    # so multiple instances can share the service without port conflicts)
    health_port: int = 8001

    # Unique instance id used for the heartbeat key worker:{instance_id}
    instance_id: str = f"{socket.gethostname()}-{os.getpid()}"

    # Redis (same instance as api-server)
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    task_queue: str = "transcode:tasks"
    event_queue: str = "transcode:events"

    # Retry policy for ffmpeg subprocess failures
    max_retries: int = 3
