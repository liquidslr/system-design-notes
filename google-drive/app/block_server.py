"""
Block Server — splits data into fixed-size blocks, computes SHA-256,
stores via ObjectStore. Provides dedup/missing-hash queries.
No awareness of users or files — pure block mechanics.
"""
import hashlib
from .config import DriveConfig
from .object_store import ObjectStore


class BlockServer:
    def __init__(self, config: DriveConfig, store: ObjectStore):
        self._config = config
        self._store = store

    @staticmethod
    def compute_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def split(self, data: bytes) -> tuple[list[str], list[bytes]]:
        """Split data into blocks of config.block_size. Returns (hashes, raw_blocks)."""
        size = self._config.block_size
        if not data:
            return [], []
        blocks = [data[i:i + size] for i in range(0, len(data), size)]
        hashes = [self.compute_hash(b) for b in blocks]
        return hashes, blocks

    def store_block(self, block_hash: str, data: bytes) -> bool:
        """Store block; verify hash integrity. Returns True if new, False if dedup hit."""
        if self.compute_hash(data) != block_hash:
            raise ValueError(f"Hash mismatch: expected {block_hash}, got {self.compute_hash(data)}")
        return self._store.put_if_absent(block_hash, data)

    def which_hashes_missing(self, hashes: list[str]) -> list[str]:
        """Return subset of hashes NOT yet in storage."""
        return [h for h in hashes if not self._store.exists(h)]

    def get_block(self, block_hash: str) -> bytes | None:
        return self._store.get(block_hash)

    def delete_block(self, block_hash: str) -> None:
        self._store.delete(block_hash)

    def reassemble(self, hashes: list[str]) -> bytes:
        """Concatenate blocks in order to reconstruct file content."""
        parts = []
        for h in hashes:
            data = self._store.get(h)
            if data is None:
                raise FileNotFoundError(f"Block missing: {h}")
            parts.append(data)
        return b"".join(parts)
