"""Proximity Service Configuration — mirrors Chapter 16 design."""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProximityConfig:
    # Geohash precision (per chapter table): length 6 ≈ ±1.2 km cells
    default_precision: int = 6
    # Search defaults
    default_radius_m: int = 5000
    max_radius_m: int = 50000
    # Quadtree parameters (chapter: split when a node has >100 businesses)
    quadtree_capacity: int = 100
    quadtree_max_depth: int = 12
    # Cache
    cache_max_size: int = 1024

    # Paths
    data_dir: Path = field(default_factory=lambda: Path("data/proximity"))
    db_filename: str = "proximity.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 9300

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename
