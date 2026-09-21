"""
News Feed System Configuration

Design doc references:
- 10 million DAU
- Users can have up to 5,000 friends
- Feed sorted in reverse chronological order
- Fanout on Write (hybrid for celebrities)
"""
from dataclasses import dataclass, field


@dataclass
class FeedConfig:
    # --- Database ---
    db_path: str = "news_feed.db"

    # --- Cache ---
    feed_cache_max_size: int = 10000         # Max post IDs per user's feed
    content_cache_max_size: int = 5000       # Max cached posts
    graph_cache_max_size: int = 5000         # Max cached friend lists
    action_cache_max_size: int = 5000        # Max cached actions
    counter_cache_max_size: int = 5000       # Max cached counters

    # --- Fanout ---
    fanout_threshold: int = 500              # Hybrid: users with >500 friends use pull model
    fanout_worker_count: int = 3             # Number of fanout workers
    fanout_batch_size: int = 100             # Batch size for fanout

    # --- Feed ---
    feed_page_size: int = 20                 # Posts per page
    max_feed_length: int = 800               # Max posts in feed cache per user

    # --- Rate Limiting ---
    posts_per_hour_limit: int = 30

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 9100
