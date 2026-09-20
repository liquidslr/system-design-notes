"""Google Drive System Configuration — mirrors Chapter 15 design."""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DriveConfig:
    # --- Storage ---
    block_size: int = 4 * 1024 * 1024           # 4 MB per chapter spec
    default_quota_bytes: int = 10 * 1024**3     # 10 GB free tier
    max_file_size_bytes: int = 10 * 1024**3     # 10 GB max file
    max_versions_kept: int = 100                 # Revision cap per file

    # --- Paths ---
    data_dir: Path = field(default_factory=lambda: Path("data/google-drive"))
    db_filename: str = "drive_metadata.db"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 9200
    long_poll_timeout_sec: float = 30.0

    # Derived ---
    @property
    def blocks_dir(self) -> Path:
        return self.data_dir / "blocks"

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename
