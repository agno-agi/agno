from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.db.mongo.schemas import get_collection_indexes


@pytest.fixture
def mock_sync_db():
    db = MagicMock()
    db.list_collection_names.return_value = []
    return db


@pytest.fixture
def mock_sync_client(mock_sync_db):
    client = MagicMock()
    client.append_metadata = MagicMock()
    client.__getitem__.return_value = mock_sync_db
    return client


@pytest.fixture
def async_mongo_db():
    return AsyncMongoDb(
        db_url="mongodb://localhost:27017",
        db_name="test_db",
    )


def test_mongo_constructor_maps_scheduler_collections(mock_sync_client):
    db = MongoDb(
        db_client=mock_sync_client,  # type: ignore[arg-type]
        db_name="test_db",
        schedules_collection="custom_schedules",
        schedule_runs_collection="custom_schedule_runs",
    )
    assert db.schedules_table_name == "custom_schedules"
    assert db.schedule_runs_table_name == "custom_schedule_runs"


def test_mongo_get_schedule_run_returns_doc_without_mongo_id(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one.return_value = {"_id": "mongo-id", "id": "run-1", "status": "completed"}
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    result = db.get_schedule_run("run-1")

    assert result == {"id": "run-1", "status": "completed"}


def test_mongo_get_schedule_run_missing_returns_none(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one.return_value = None
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    assert db.get_schedule_run("missing-run") is None


def test_mongo_get_collection_supports_scheduler_tables(monkeypatch: pytest.MonkeyPatch, mock_sync_client):
    db = MongoDb(
        db_client=mock_sync_client,  # type: ignore[arg-type]
        db_name="test_db",
        schedules_collection="custom_schedules",
        schedule_runs_collection="custom_schedule_runs",
    )

    calls = []

    def _fake_get_or_create_collection(collection_name: str, collection_type: str, create_collection_if_not_found=True):
        calls.append((collection_name, collection_type, create_collection_if_not_found))
        return Mock()

    monkeypatch.setattr(db, "_get_or_create_collection", _fake_get_or_create_collection)

    schedules_collection = db._get_collection("schedules")
    schedule_runs_collection = db._get_collection("schedule_runs")

    assert schedules_collection is not None
    assert schedule_runs_collection is not None
    assert ("custom_schedules", "schedules", True) in calls
    assert ("custom_schedule_runs", "schedule_runs", True) in calls


def test_mongo_create_all_tables_includes_scheduler_tables(monkeypatch: pytest.MonkeyPatch, mock_sync_client):
    db = MongoDb(
        db_client=mock_sync_client,  # type: ignore[arg-type]
        db_name="test_db",
        schedules_collection="custom_schedules",
        schedule_runs_collection="custom_schedule_runs",
    )

    requested_collections = []
    monkeypatch.setattr(db, "table_exists", lambda table_name: False)

    def _fake_get_collection(table_type: str, create_collection_if_not_found=True):
        requested_collections.append((table_type, create_collection_if_not_found))
        return Mock()

    monkeypatch.setattr(db, "_get_collection", _fake_get_collection)

    db._create_all_tables()

    assert ("schedules", True) in requested_collections
    assert ("schedule_runs", True) in requested_collections


def test_scheduler_index_schemas_registered():
    schedules_indexes = get_collection_indexes("schedules")
    schedule_runs_indexes = get_collection_indexes("schedule_runs")

    assert any(i.get("key") == "id" and i.get("unique") for i in schedules_indexes)
    assert any(i.get("key") == "name" and i.get("unique") for i in schedules_indexes)
    assert any(i.get("key") == "id" and i.get("unique") for i in schedule_runs_indexes)
    assert any(i.get("key") == "schedule_id" for i in schedule_runs_indexes)


def test_async_mongo_constructor_maps_scheduler_collections():
    db = AsyncMongoDb(
        db_url="mongodb://localhost:27017",
        db_name="test_db",
        schedules_collection="custom_schedules",
        schedule_runs_collection="custom_schedule_runs",
    )
    assert db.schedules_table_name == "custom_schedules"
    assert db.schedule_runs_table_name == "custom_schedule_runs"


@pytest.mark.asyncio
async def test_async_mongo_get_schedule_run_returns_doc_without_mongo_id(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one.return_value = {"_id": "mongo-id", "id": "run-1", "status": "completed"}
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    result = await db.get_schedule_run("run-1")

    assert result == {"id": "run-1", "status": "completed"}


@pytest.mark.asyncio
async def test_async_mongo_get_schedule_run_missing_returns_none(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one.return_value = None
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    assert await db.get_schedule_run("missing-run") is None
