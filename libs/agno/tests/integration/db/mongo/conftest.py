"""Fixtures for sync MongoDb integration tests"""

import uuid

import pytest

# Require the sync driver; mirror async_mongo/conftest.py's import guard.
try:
    import pymongo

    PYMONGO_AVAILABLE = True
except ImportError:
    PYMONGO_AVAILABLE = False

if not PYMONGO_AVAILABLE:
    pytest.skip("pymongo not installed", allow_module_level=True)

from agno.db.mongo import MongoDb

MONGO_URL = "mongodb://mongoadmin:secret@localhost:27017"


@pytest.fixture
def mongo_db_real():
    """MongoDb against the real MongoDB at localhost:27017 (mongoadmin/secret).

    A dedicated database per test, dropped afterwards. If the service is down
    the first operation errors — deliberately no reachability skip.
    """
    db_name = f"test_agno_mongo_{uuid.uuid4().hex[:8]}"
    db = MongoDb(db_url=MONGO_URL, db_name=db_name)

    yield db

    client = pymongo.MongoClient(MONGO_URL)
    client.drop_database(db_name)
    client.close()
