from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import pytest

pytest.importorskip("pymongo")

from agno.db.mongo import AsyncMongoDb  # noqa: E402
from agno.exceptions import MigrationRequiredError  # noqa: E402


class _FakeAsyncCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.find_one_calls = 0
        self.update_one_calls = 0

    async def index_information(self) -> Dict[str, Any]:
        return {}

    async def create_index(self, *_args: Any, **_kwargs: Any) -> str:
        return "index"

    async def find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.find_one_calls += 1
        return self.documents.get(str(query.get("table_name")))

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], *, upsert: bool = False) -> None:
        self.update_one_calls += 1
        assert upsert is True
        self.documents[str(query["table_name"])] = dict(update["$set"])


class _FakeAsyncDatabase:
    def __init__(self, *, existing: Optional[set[str]] = None) -> None:
        self.collections: Dict[str, _FakeAsyncCollection] = {
            name: _FakeAsyncCollection(name) for name in (existing or set())
        }
        self.create_calls = 0

    def __getitem__(self, name: str) -> _FakeAsyncCollection:
        return self.collections.setdefault(name, _FakeAsyncCollection(name))

    async def list_collection_names(self) -> list[str]:
        return list(self.collections)

    async def create_collection(self, name: str) -> _FakeAsyncCollection:
        self.create_calls += 1
        collection = _FakeAsyncCollection(name)
        self.collections[name] = collection
        return collection


def _new_db(database: _FakeAsyncDatabase) -> AsyncMongoDb:
    db = AsyncMongoDb(db_url="mongodb://unused", db_name="test")
    db._client = object()
    db._database = database
    db._event_loop = asyncio.get_running_loop()
    return db


@pytest.mark.asyncio
async def test_concurrent_fresh_collection_is_created_and_stamped_once() -> None:
    database = _FakeAsyncDatabase()
    db = _new_db(database)

    collections = await asyncio.gather(*(db._get_collection("sessions") for _ in range(8)))

    assert all(collection is collections[0] for collection in collections)
    assert database.create_calls == 1
    versions = database[db.versions_table_name]
    assert versions.update_one_calls == 1
    assert await db.get_latest_schema_version(db.session_table_name) == "3.0.0"


@pytest.mark.asyncio
async def test_stale_collection_refuses_then_same_instance_accepts_migrated_stamp() -> None:
    database = _FakeAsyncDatabase(existing={"agno_sessions"})
    db = _new_db(database)

    with pytest.raises(MigrationRequiredError):
        await db._get_collection("sessions")

    await db.upsert_schema_version(db.session_table_name, "3.0.0")
    collection = await db._get_collection("sessions")

    assert collection is database[db.session_table_name]
    find_calls = database[db.versions_table_name].find_one_calls
    assert await db._get_collection("sessions") is collection
    assert database[db.versions_table_name].find_one_calls == find_calls


@pytest.mark.asyncio
async def test_absent_read_only_probe_does_not_create_or_stamp() -> None:
    database = _FakeAsyncDatabase()
    db = _new_db(database)

    assert await db._get_collection("sessions", create_collection_if_not_found=False) is None
    assert database.create_calls == 0
    assert db.versions_table_name not in database.collections
