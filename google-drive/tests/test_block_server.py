"""Tests for ObjectStore and BlockServer."""
import hashlib
import pytest
from app.object_store import ObjectStore
from app.block_server import BlockServer
from app.config import DriveConfig


class TestObjectStore:
    def test_put_and_get(self, store):
        store.put("abc123", b"hello world")
        assert store.get("abc123") == b"hello world"

    def test_exists(self, store):
        assert not store.exists("deadbeef")
        store.put("deadbeef", b"x")
        assert store.exists("deadbeef")

    def test_delete(self, store):
        store.put("todelete", b"data")
        store.delete("todelete")
        assert not store.exists("todelete")

    def test_put_if_absent_dedup(self, store):
        store.put("dup", b"first")
        was_new = store.put_if_absent("dup", b"second")
        assert was_new is False
        assert store.get("dup") == b"first"

    def test_total_stored_bytes(self, store):
        store.put("a", b"12345")
        store.put("b", b"67890")
        assert store.total_stored_bytes() == 10


class TestBlockServer:
    def test_split(self, block_server):
        data = b"a" * 25  # block_size=10 → 3 blocks
        hashes, blocks = block_server.split(data)
        assert len(blocks) == 3
        assert len(hashes) == 3

    def test_store_and_dedup(self, block_server):
        chunk = b"hello"
        h = hashlib.sha256(chunk).hexdigest()
        assert block_server.store_block(h, chunk) is True   # new
        assert block_server.store_block(h, chunk) is False  # dedup

    def test_which_hashes_missing(self, block_server):
        chunk = b"exists"
        h = hashlib.sha256(chunk).hexdigest()
        block_server.store_block(h, chunk)
        other = hashlib.sha256(b"absent").hexdigest()
        missing = block_server.which_hashes_missing([h, other])
        assert missing == [other]

    def test_hash_mismatch_raises(self, block_server):
        with pytest.raises(ValueError, match="Hash mismatch"):
            block_server.store_block("wronghash", b"realdata")

    def test_reassemble(self, block_server):
        data = b"abcdefghij" + b"klmnopqrst" + b"uvwxyz"
        hashes, blocks = block_server.split(data)
        for h, b in zip(hashes, blocks):
            block_server.store_block(h, b)
        assert block_server.reassemble(hashes) == data
