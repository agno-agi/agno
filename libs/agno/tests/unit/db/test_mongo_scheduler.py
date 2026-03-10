from typing import Any, Dict, Optional
from unittest.mock import Mock

import pytest

from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.db.mongo.schemas import get_collection_indexes


class _DummySyncCollection:
    def __init__(self, doc: Optional[Dict[str, Any]] = None):
        self._doc = doc

    def create_index(self, *args, **kwargs):
        return None

    def find_one(self, query: Dict[str, Any]):
        if self._doc is None:
            return None
        if self._doc.get("id") == query.get("id"):
            return dict(self._doc)
        return None


class _DummySyncDatabase:
    def __init__(self):
        self._collections: Dict[str, _DummySyncCollection] = {}

    def list_collection_names(self):
        return list(self._collections.keys())

    def __getitem__(self, name: str):
        if name not in self._collections:
            self._collections[name] = _DummySyncCollection()
        return self._collections[name]


class _DummySyncClient:
    def __init__(self):
        self._db = _DummySyncDatabase()

    def append_metadata(self, *args, **kwargs):
        return None

    def __getitem__(self, name: str):
        return self._db

    def close(self):
        return None


class _DummyAsyncCollection:
    def __init__(self, doc: Optional[Dict[str, Any]] = None):
        self._doc = doc

    async def find_one(self, query: Dict[str, Any]):
        if self._doc is None:
            return None
        if self._doc.get("id") == query.get("id"):
            return dict(self._doc)
        return None


def test_mongo_constructor_maps_scheduler_collections():
    db = MongoDb(
        db_client=_DummySyncClient(),  # type: ignore[arg-type]
        db_name="test_db",
        schedules_collection="custom_schedules",
        schedule_runs_collection="custom_schedule_runs",
    )
    assert db.schedules_table_name == "custom_schedules"
    assert db.schedule_runs_table_name == "custom_schedule_runs"


def test_mongo_get_schedule_run_returns_doc_without_mongo_id(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=_DummySyncClient(), db_name="test_db")  # type: ignore[arg-type]
    collection = _DummySyncCollection(doc={"_id": "mongo-id", "id": "run-1", "status": "completed"})
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    result = db.get_schedule_run("run-1")

    assert result == {"id": "run-1", "status": "completed"}


def test_mongo_get_schedule_run_missing_returns_none(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=_DummySyncClient(), db_name="test_db")  # type: ignore[arg-type]
    collection = _DummySyncCollection(doc=None)
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    assert db.get_schedule_run("missing-run") is None


def test_mongo_get_collection_supports_scheduler_tables(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(
        db_client=_DummySyncClient(),  # type: ignore[arg-type]
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


def test_mongo_create_all_tables_includes_scheduler_tables(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(
        db_client=_DummySyncClient(),  # type: ignore[arg-type]
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
    db = AsyncMongoDb(
        db_url="mongodb://localhost:27017",
        db_name="test_db",
    )
    collection = _DummyAsyncCollection(doc={"_id": "mongo-id", "id": "run-1", "status": "completed"})

    async def _fake_get_collection(table_type: str, create_collection_if_not_found=True):
        return collection

    monkeypatch.setattr(db, "_get_collection", _fake_get_collection)

    result = await db.get_schedule_run("run-1")

    assert result == {"id": "run-1", "status": "completed"}


@pytest.mark.asyncio
async def test_async_mongo_get_schedule_run_missing_returns_none(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(
        db_url="mongodb://localhost:27017",
        db_name="test_db",
    )
    collection = _DummyAsyncCollection(doc=None)

    async def _fake_get_collection(table_type: str, create_collection_if_not_found=True):
        return collection

    monkeypatch.setattr(db, "_get_collection", _fake_get_collection)

    assert await db.get_schedule_run("missing-run") is None
