"""
Configuration for the Search Autocomplete System.
"""
from dataclasses import dataclass, field


@dataclass
class Config:
    # Database
    db_path: str = "data/autocomplete.db"

    # Trie settings
    max_prefix_length: int = 50
    top_k: int = 5
    allowed_chars: str = "abcdefghijklmnopqrstuvwxyz"

    # Aggregator settings
    aggregation_interval_seconds: int = 60

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000

    # Seed data for demo
    seed_queries: dict = field(default_factory=lambda: {
        "twitter": 1000,
        "twilight": 600,
        "twitch": 800,
        "tweet": 500,
        "twinkle": 200,
        "two": 300,
        "twenty": 250,
        "twin": 180,
        "switch": 700,
        "swift": 650,
        "swim": 300,
        "sweet": 400,
        "google": 2000,
        "gmail": 1500,
        "github": 1200,
        "google maps": 900,
        "google translate": 850,
        "google drive": 700,
        "facebook": 1800,
        "flutter": 500,
        "flask": 400,
        "flower": 350,
        "python": 1600,
        "pygame": 400,
        "pinterest": 600,
        "pizza": 500,
        "puzzle": 300,
        "amazon": 1400,
        "apple": 1300,
        "airbnb": 700,
        "anime": 900,
        "algorithm": 500,
        "chatgpt": 1100,
        "chess": 600,
        "chrome": 800,
        "calculator": 400,
        "docker": 700,
        "django": 500,
        "disney": 600,
        "data science": 450,
        "leetcode": 800,
        "linkedin": 700,
        "laptop": 500,
        "love": 400,
        "machine learning": 750,
        "minecraft": 900,
        "music": 600,
        "movie": 500,
        "netflix": 1200,
        "nodejs": 500,
        "nba": 600,
        "news": 400,
        "react": 900,
        "reddit": 800,
        "roblox": 700,
        "recipe": 400,
        "spotify": 800,
        "stackoverflow": 600,
        "samsung": 500,
        "sushi": 300,
        "tiktok": 1000,
        "tesla": 600,
        "travel": 500,
        "typescript": 400,
        "uber": 500,
        "universe": 300,
        "unity": 400,
        "youtube": 1500,
        "yahoo": 400,
        "yoga": 300,
    })


config = Config()
