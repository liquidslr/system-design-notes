"""
Local content-addressed blob store simulating S3.
Blocks are stored at {blocks_dir}/{hash}. Pure key->bytes store.
In production: Amazon S3 with cross-region replication + Glacier cold tier.
"""
from pathlib import Path
from .config import DriveConfig


class ObjectStore:
    def __init__(self, config: DriveConfig):
        self._root = config.blocks_dir
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._root / key

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def put(self, key: str, data: bytes) -> None:
        self._path(key).write_bytes(data)

    def put_if_absent(self, key: str, data: bytes) -> bool:
        """Returns True if newly stored, False if already existed (dedup hit)."""
        p = self._path(key)
        if p.is_file():
            return False
        p.write_bytes(data)
        return True

    def get(self, key: str) -> bytes | None:
        p = self._path(key)
        if p.is_file():
            return p.read_bytes()
        return None

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.is_file():
            p.unlink()

    def total_stored_bytes(self) -> int:
        return sum(f.stat().st_size for f in self._root.iterdir() if f.is_file())
