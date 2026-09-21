"""
Notification System Configuration

Design doc references:
- Push: 10M/day, SMS: 1M/day, Email: 5M/day
- Soft real-time with minimal delays
- Opt-out support per channel
- Rate limiting, deduplication, retry mechanism
"""
from dataclasses import dataclass, field


@dataclass
class NotificationConfig:
    # --- Database ---
    db_path: str = "notification_system.db"

    # --- Rate Limiting ---
    rate_limit_per_user_per_hour: int = 30
    rate_limit_per_user_per_day: int = 100

    # --- Retry ---
    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    retry_backoff_multiplier: float = 2.0

    # --- Queue ---
    queue_poll_interval: float = 0.5
    num_workers: int = 3

    # --- Deduplication ---
    dedup_ttl_seconds: int = 3600  # 1 hour

    # --- Third-party API keys (demo placeholders) ---
    apns_key: str = ""
    apns_secret: str = ""
    fcm_server_key: str = ""
    twilio_sid: str = ""
    twilio_token: str = ""
    twilio_from_number: str = ""
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "noreply@example.com"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 9000
