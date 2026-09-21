"""Shared fixtures for Proximity Service tests."""
import pytest
import pytest_asyncio
from app.business_service import BusinessService, SpatialIndex
from app.cache import CacheLayer
from app.config import ProximityConfig
from app.database import Database
from app.lbs_service import LBSService


@pytest.fixture
def config(tmp_path):
    cfg = ProximityConfig()
    cfg.data_dir = tmp_path
    return cfg


@pytest_asyncio.fixture
async def db(config):
    database = Database(config)
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def cache(config):
    return CacheLayer(config.cache_max_size)


@pytest.fixture
def index(config):
    return SpatialIndex(config)


@pytest.fixture
def business_svc(config, db, index, cache):
    return BusinessService(config, db, index, cache)


@pytest.fixture
def lbs_svc(config, db, index, cache):
    return LBSService(config, db, index, cache)
