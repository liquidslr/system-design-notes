"""Shared fixtures for Google Drive tests."""
import pytest
import pytest_asyncio
from app.config import DriveConfig
from app.database import Database
from app.object_store import ObjectStore
from app.block_server import BlockServer
from app.notification import NotificationCenter
from app.api_service import ApiService


@pytest.fixture
def config(tmp_path):
    cfg = DriveConfig()
    cfg.data_dir = tmp_path
    cfg.block_size = 10  # small blocks for fast tests
    return cfg


@pytest_asyncio.fixture
async def db(config):
    database = Database(config)
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def store(config):
    return ObjectStore(config)


@pytest.fixture
def block_server(config, store):
    return BlockServer(config, store)


@pytest_asyncio.fixture
async def notifier(db):
    return NotificationCenter(db)


@pytest_asyncio.fixture
async def svc(config, db, block_server, store, notifier):
    """ApiService with a pre-inserted test user."""
    import time
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await db.insert_user("u_test", "test@example.com", "h", "s", 1024 * 1024, now)
    await db.insert_user("u_bob", "bob@test.com", "h", "s", 1024 * 1024, now)
    return ApiService(config, db, block_server, store, notifier)
