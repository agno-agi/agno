from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.db.mongo.schemas import get_collection_indexes
from agno.db.mongo.utils import create_collection_indexes, create_collection_indexes_async


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
    collection.find_one.return_value = {"_id": "mongo-id", "id": "run-1", "status": "success"}
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    result = db.get_schedule_run("run-1")

    assert result == {"id": "run-1", "status": "success"}


def test_mongo_get_schedule_run_missing_returns_none(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one.return_value = None
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    assert db.get_schedule_run("missing-run") is None


def test_mongo_get_schedule_returns_doc_without_mongo_id(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one.return_value = {"_id": "mongo-id", "id": "sched-1", "name": "Nightly"}
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    result = db.get_schedule("sched-1")

    assert result == {"id": "sched-1", "name": "Nightly"}


def test_mongo_get_schedule_by_name_returns_doc_without_mongo_id(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one.return_value = {"_id": "mongo-id", "id": "sched-1", "name": "Nightly"}
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    result = db.get_schedule_by_name("Nightly")

    assert result == {"id": "sched-1", "name": "Nightly"}


def test_mongo_get_schedules_returns_paginated_items_and_total(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.count_documents.return_value = 2

    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = [
        {"_id": "mongo-1", "id": "sched-1", "name": "Nightly"},
        {"_id": "mongo-2", "id": "sched-2", "name": "Hourly"},
    ]
    collection.find.return_value = cursor
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    schedules, total = db.get_schedules(enabled=True, limit=10, page=1)

    assert total == 2
    assert schedules == [
        {"id": "sched-1", "name": "Nightly"},
        {"id": "sched-2", "name": "Hourly"},
    ]
    collection.count_documents.assert_called_once_with({"enabled": True})


def test_mongo_create_schedule_inserts_and_returns_data(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    monkeypatch.setattr(
        db,
        "_get_collection",
        lambda table_type, create_collection_if_not_found=True: collection,
    )

    schedule_data = {"id": "sched-1", "name": "Nightly"}
    result = db.create_schedule(schedule_data)

    collection.insert_one.assert_called_once_with(schedule_data)
    assert result == schedule_data


def test_mongo_update_schedule_updates_and_returns_schedule(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    update_result = Mock()
    update_result.matched_count = 1
    collection.update_one.return_value = update_result
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)
    monkeypatch.setattr(db, "get_schedule", lambda schedule_id: {"id": schedule_id, "name": "Updated"})

    result = db.update_schedule("sched-1", name="Updated")

    assert result == {"id": "sched-1", "name": "Updated"}
    assert collection.update_one.call_count == 1


def test_mongo_disable_schedules_for_target_is_atomic_and_scoped(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    update_result = Mock(modified_count=101)
    collection.update_many.return_value = update_result
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    disabled = db.disable_schedules_for_target(
        "agent",
        "agent-a",
        managed_by="studio",
    )

    assert disabled == 101
    query, update = collection.update_many.call_args.args
    assert query == {
        "managed_by": "studio",
        "target_type": "agent",
        "target_id": "agent-a",
        "enabled": True,
    }
    assert update["$set"]["enabled"] is False
    assert isinstance(update["$set"]["updated_at"], int)


def test_mongo_delete_schedule_cascades_runs(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    schedules_collection = Mock()
    schedule_runs_collection = Mock()
    delete_result = Mock()
    delete_result.deleted_count = 1
    schedules_collection.delete_one.return_value = delete_result

    def _fake_get_collection(table_type):
        if table_type == "schedules":
            return schedules_collection
        if table_type == "schedule_runs":
            return schedule_runs_collection
        return None

    monkeypatch.setattr(db, "_get_collection", _fake_get_collection)

    deleted = db.delete_schedule("sched-1")

    assert deleted is True
    schedule_runs_collection.delete_many.assert_called_once_with({"schedule_id": "sched-1"})
    schedules_collection.delete_one.assert_called_once_with({"id": "sched-1"})


def test_mongo_claim_due_schedule_returns_claimed_schedule(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one_and_update.return_value = {
        "_id": "mongo-id",
        "id": "sched-1",
        "enabled": True,
        "next_run_at": 123,
        "locked_by": "worker-1",
    }
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    result = db.claim_due_schedule("worker-1", lock_grace_seconds=300)

    assert result == {
        "id": "sched-1",
        "enabled": True,
        "next_run_at": 123,
        "locked_by": "worker-1",
    }
    assert collection.find_one_and_update.call_count == 1


def test_mongo_claims_due_cron_without_consuming_pending_manual_work(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one_and_update.side_effect = [
        None,
        None,
        {
            "_id": "mongo-id",
            "id": "sched-1",
            "enabled": True,
            "next_run_at": 123,
            "pending_trigger_count": 1,
            "locked_by": "worker-1",
        },
    ]
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    result = db.claim_due_schedule("worker-1", lock_grace_seconds=300)

    assert result is not None and result["pending_trigger_count"] == 1
    recovery_query, recovery_update = collection.find_one_and_update.call_args_list[0].args[:2]
    manual_query, manual_update = collection.find_one_and_update.call_args_list[1].args[:2]
    cron_query, cron_update = collection.find_one_and_update.call_args_list[2].args[:2]
    assert recovery_query["manual_trigger_claimed"] is True
    assert "$inc" not in recovery_update
    assert "$nor" in manual_query
    assert "$inc" in manual_update
    assert "next_run_at" in cron_query
    assert "$inc" not in cron_update


def test_mongo_recovers_stale_manual_claim_without_consuming_another_trigger(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one_and_update.return_value = {
        "_id": "mongo-id",
        "id": "sched-1",
        "enabled": True,
        "next_run_at": 123,
        "pending_trigger_count": 0,
        "manual_trigger_claimed": True,
        "locked_by": "recovery-worker",
        "locked_at": 456,
    }
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    recovered = db.claim_due_schedule("recovery-worker", lock_grace_seconds=300)

    assert recovered is not None and recovered["manual_trigger_claimed"] is True
    query, update = collection.find_one_and_update.call_args.args[:2]
    assert query["manual_trigger_claimed"] is True
    assert "$inc" not in update

    collection.update_one.return_value = Mock(matched_count=1)
    assert db.release_schedule("sched-1", worker_id="recovery-worker", locked_at=456) is True
    release_query, release_update = collection.update_one.call_args.args
    assert release_query == {"id": "sched-1", "locked_by": "recovery-worker", "locked_at": 456}
    assert release_update["$set"]["manual_trigger_claimed"] is False
    assert "next_run_at" not in release_update["$set"]


def test_mongo_renews_only_the_exact_claim_fence(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.find_one_and_update.return_value = {"id": "sched-1"}
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)
    monkeypatch.setattr("agno.db.mongo.mongo.time.time", lambda: 123)

    renewed_at = db.renew_schedule_claim("sched-1", worker_id="worker-1", locked_at=123)

    assert renewed_at == 124
    query, update = collection.find_one_and_update.call_args.args
    assert query == {"id": "sched-1", "locked_by": "worker-1", "locked_at": 123}
    assert update["$set"]["locked_at"] == renewed_at
    assert "manual_trigger_claimed" not in update["$set"]
    assert "pending_trigger_count" not in update["$set"]
    collection.update_one.side_effect = [Mock(matched_count=0), Mock(matched_count=1)]
    assert not db.release_schedule("sched-1", worker_id="worker-1", locked_at=123)
    assert db.release_schedule("sched-1", worker_id="worker-1", locked_at=renewed_at)


def test_mongo_release_schedule_unlocks_and_returns_true(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    update_result = Mock()
    update_result.matched_count = 1
    collection.update_one.return_value = update_result
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    released = db.release_schedule("sched-1", next_run_at=999)

    assert released is True
    assert collection.update_one.call_count == 1


def test_mongo_create_schedule_run_inserts_and_returns_data(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    monkeypatch.setattr(
        db,
        "_get_collection",
        lambda table_type, create_collection_if_not_found=True: collection,
    )

    run_data = {"id": "run-1", "schedule_id": "sched-1", "status": "running"}
    result = db.create_schedule_run(run_data)

    collection.insert_one.assert_called_once_with(run_data)
    assert result == run_data


def test_mongo_update_schedule_run_updates_and_returns_run(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    update_result = Mock()
    update_result.matched_count = 1
    collection.update_one.return_value = update_result
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)
    monkeypatch.setattr(db, "get_schedule_run", lambda run_id: {"id": run_id, "status": "success"})

    result = db.update_schedule_run("run-1", status="success")

    assert result == {"id": "run-1", "status": "success"}
    collection.update_one.assert_called_once()


def test_mongo_get_schedule_runs_returns_paginated_items_and_total(monkeypatch: pytest.MonkeyPatch):
    db = MongoDb(db_client=MagicMock(), db_name="test_db")  # type: ignore[arg-type]
    collection = Mock()
    collection.count_documents.return_value = 2

    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = [
        {"_id": "mongo-1", "id": "run-1", "schedule_id": "sched-1"},
        {"_id": "mongo-2", "id": "run-2", "schedule_id": "sched-1"},
    ]
    collection.find.return_value = cursor
    monkeypatch.setattr(db, "_get_collection", lambda table_type: collection)

    runs, total = db.get_schedule_runs("sched-1", limit=20, page=1)

    assert total == 2
    assert runs == [
        {"id": "run-1", "schedule_id": "sched-1"},
        {"id": "run-2", "schedule_id": "sched-1"},
    ]
    collection.count_documents.assert_called_once_with({"schedule_id": "sched-1"})


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
    assert any(
        i.get("key") == [("name", 1), ("managed_by", 1)]
        and i.get("unique")
        and i.get("name") == "uq_generic_name"
        and i.get("partialFilterExpression") == {"managed_by": None}
        for i in schedules_indexes
    )
    assert any(
        i.get("key") == [("owner_actor_id", 1), ("name", 1)]
        and i.get("unique")
        and i.get("name") == "uq_studio_owner_name"
        for i in schedules_indexes
    )
    assert any(i.get("key") == "pending_trigger_count" for i in schedules_indexes)
    assert any(i.get("key") == "manual_trigger_claimed" for i in schedules_indexes)
    assert any(i.get("key") == "id" and i.get("unique") for i in schedule_runs_indexes)
    assert any(i.get("key") == "schedule_id" for i in schedule_runs_indexes)


def test_schedule_index_migration_fails_loudly_before_dropping_legacy_authority():
    collection = MagicMock()
    collection.list_indexes.return_value = [{"name": "name_1", "key": {"name": 1}, "unique": True}]

    def create_index(_keys, **options):
        if options.get("name") == "uq_studio_owner_name":
            raise RuntimeError("cannot build actor index")

    collection.create_index.side_effect = create_index

    with pytest.raises(RuntimeError, match="actor index"):
        create_collection_indexes(collection, "schedules")

    collection.drop_index.assert_not_called()


@pytest.mark.asyncio
async def test_async_schedule_index_migration_fails_loudly_before_dropping_legacy_authority():
    class AsyncCursor:
        def __init__(self, rows):
            self.rows = iter(rows)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.rows)
            except StopIteration:
                raise StopAsyncIteration

    collection = MagicMock()
    collection.list_indexes = AsyncMock(
        return_value=AsyncCursor([{"name": "name_1", "key": {"name": 1}, "unique": True}])
    )

    async def create_index(_keys, **options):
        if options.get("name") == "uq_studio_owner_name":
            raise RuntimeError("cannot build actor index")

    collection.create_index = AsyncMock(side_effect=create_index)
    collection.drop_index = AsyncMock()

    with pytest.raises(RuntimeError, match="actor index"):
        await create_collection_indexes_async(collection, "schedules")

    collection.drop_index.assert_not_awaited()


def test_schedule_index_migration_uses_distinct_key_before_dropping_legacy_authority():
    collection = MagicMock()
    collection.list_indexes.return_value = [{"name": "name_1", "key": {"name": 1}, "unique": True}]
    created_names = []

    def create_index(_keys, **options):
        created_names.append(options.get("name"))

    def drop_index(index_name):
        assert "uq_generic_name" in created_names
        assert "uq_studio_owner_name" in created_names
        assert index_name == "name_1"

    collection.create_index.side_effect = create_index
    collection.drop_index.side_effect = drop_index

    create_collection_indexes(collection, "schedules")

    # Pin the exact compound key: pre-5.0 servers reject a second index that
    # reuses the legacy {name: 1} key pattern, so create-before-drop is only
    # safe because the replacement's key and name differ from the legacy one's.
    generic_call = next(
        call for call in collection.create_index.call_args_list if call.kwargs.get("name") == "uq_generic_name"
    )
    assert generic_call.args[0] == [("name", 1), ("managed_by", 1)]
    collection.drop_index.assert_called_once_with("name_1")


@pytest.mark.asyncio
async def test_async_schedule_index_migration_uses_distinct_key_before_dropping_legacy_authority():
    class AsyncCursor:
        def __init__(self, rows):
            self.rows = iter(rows)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.rows)
            except StopIteration:
                raise StopAsyncIteration

    collection = MagicMock()
    collection.list_indexes = AsyncMock(
        return_value=AsyncCursor([{"name": "name_1", "key": {"name": 1}, "unique": True}])
    )
    created_names = []

    async def create_index(_keys, **options):
        created_names.append(options.get("name"))

    async def drop_index(index_name):
        assert "uq_generic_name" in created_names
        assert "uq_studio_owner_name" in created_names
        assert index_name == "name_1"

    collection.create_index = AsyncMock(side_effect=create_index)
    collection.drop_index = AsyncMock(side_effect=drop_index)

    await create_collection_indexes_async(collection, "schedules")

    generic_call = next(
        call for call in collection.create_index.call_args_list if call.kwargs.get("name") == "uq_generic_name"
    )
    assert generic_call.args[0] == [("name", 1), ("managed_by", 1)]
    collection.drop_index.assert_awaited_once_with("name_1")


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
    collection.find_one.return_value = {"_id": "mongo-id", "id": "run-1", "status": "success"}
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    result = await db.get_schedule_run("run-1")

    assert result == {"id": "run-1", "status": "success"}


@pytest.mark.asyncio
async def test_async_mongo_get_schedule_run_missing_returns_none(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one.return_value = None
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    assert await db.get_schedule_run("missing-run") is None


@pytest.mark.asyncio
async def test_async_mongo_get_schedule_returns_doc_without_mongo_id(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one.return_value = {"_id": "mongo-id", "id": "sched-1", "name": "Nightly"}
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    result = await db.get_schedule("sched-1")

    assert result == {"id": "sched-1", "name": "Nightly"}


@pytest.mark.asyncio
async def test_async_mongo_get_schedule_by_name_returns_doc_without_mongo_id(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one.return_value = {"_id": "mongo-id", "id": "sched-1", "name": "Nightly"}
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    result = await db.get_schedule_by_name("Nightly")

    assert result == {"id": "sched-1", "name": "Nightly"}


@pytest.mark.asyncio
async def test_async_mongo_get_schedules_returns_paginated_items_and_total(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = MagicMock()
    collection.count_documents = AsyncMock(return_value=2)

    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(
        return_value=[
            {"_id": "mongo-1", "id": "sched-1", "name": "Nightly"},
            {"_id": "mongo-2", "id": "sched-2", "name": "Hourly"},
        ]
    )
    collection.find.return_value = cursor
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    schedules, total = await db.get_schedules(enabled=True, limit=10, page=1)

    assert total == 2
    assert schedules == [
        {"id": "sched-1", "name": "Nightly"},
        {"id": "sched-2", "name": "Hourly"},
    ]


@pytest.mark.asyncio
async def test_async_mongo_create_schedule_inserts_and_returns_data(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    schedule_data = {"id": "sched-1", "name": "Nightly"}
    result = await db.create_schedule(schedule_data)

    collection.insert_one.assert_called_once_with(schedule_data)
    assert result == schedule_data


@pytest.mark.asyncio
async def test_async_mongo_update_schedule_updates_and_returns_schedule(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    update_result = MagicMock()
    update_result.matched_count = 1
    collection.update_one.return_value = update_result
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))
    monkeypatch.setattr(db, "get_schedule", AsyncMock(return_value={"id": "sched-1", "name": "Updated"}))

    result = await db.update_schedule("sched-1", name="Updated")

    assert result == {"id": "sched-1", "name": "Updated"}
    collection.update_one.assert_called_once()


@pytest.mark.asyncio
async def test_async_mongo_disable_schedules_for_target_is_atomic_and_scoped(
    monkeypatch: pytest.MonkeyPatch,
):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.update_many.return_value = MagicMock(modified_count=2)
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    disabled = await db.disable_schedules_for_target(
        "team",
        "team-a",
        managed_by="studio",
    )

    assert disabled == 2
    query, update = collection.update_many.call_args.args
    assert query == {
        "managed_by": "studio",
        "target_type": "team",
        "target_id": "team-a",
        "enabled": True,
    }
    assert update["$set"]["enabled"] is False
    assert isinstance(update["$set"]["updated_at"], int)


@pytest.mark.asyncio
async def test_async_mongo_delete_schedule_cascades_runs(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    schedules_collection = AsyncMock()
    schedule_runs_collection = AsyncMock()
    delete_result = MagicMock()
    delete_result.deleted_count = 1
    schedules_collection.delete_one.return_value = delete_result

    async def _fake_get_collection(table_type, create_collection_if_not_found=True):
        if table_type == "schedules":
            return schedules_collection
        if table_type == "schedule_runs":
            return schedule_runs_collection
        return None

    monkeypatch.setattr(db, "_get_collection", _fake_get_collection)

    deleted = await db.delete_schedule("sched-1")

    assert deleted is True
    schedule_runs_collection.delete_many.assert_called_once_with({"schedule_id": "sched-1"})
    schedules_collection.delete_one.assert_called_once_with({"id": "sched-1"})


@pytest.mark.asyncio
async def test_async_mongo_claim_due_schedule_returns_claimed_schedule(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one_and_update.return_value = {
        "_id": "mongo-id",
        "id": "sched-1",
        "enabled": True,
        "next_run_at": 123,
        "locked_by": "worker-1",
    }
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    result = await db.claim_due_schedule("worker-1", lock_grace_seconds=300)

    assert result == {
        "id": "sched-1",
        "enabled": True,
        "next_run_at": 123,
        "locked_by": "worker-1",
    }
    collection.find_one_and_update.assert_called_once()


@pytest.mark.asyncio
async def test_async_mongo_claims_due_cron_without_consuming_pending_manual_work(
    monkeypatch: pytest.MonkeyPatch,
):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one_and_update.side_effect = [
        None,
        None,
        {
            "_id": "mongo-id",
            "id": "sched-1",
            "enabled": True,
            "next_run_at": 123,
            "pending_trigger_count": 1,
            "locked_by": "worker-1",
        },
    ]
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    result = await db.claim_due_schedule("worker-1", lock_grace_seconds=300)

    assert result is not None and result["pending_trigger_count"] == 1
    recovery_query, recovery_update = collection.find_one_and_update.call_args_list[0].args[:2]
    manual_query, manual_update = collection.find_one_and_update.call_args_list[1].args[:2]
    cron_query, cron_update = collection.find_one_and_update.call_args_list[2].args[:2]
    assert recovery_query["manual_trigger_claimed"] is True
    assert "$inc" not in recovery_update
    assert "$nor" in manual_query
    assert "$inc" in manual_update
    assert "next_run_at" in cron_query
    assert "$inc" not in cron_update


@pytest.mark.asyncio
async def test_async_mongo_recovers_stale_manual_claim_without_consuming_another_trigger(
    monkeypatch: pytest.MonkeyPatch,
):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one_and_update.return_value = {
        "_id": "mongo-id",
        "id": "sched-1",
        "enabled": True,
        "next_run_at": 123,
        "pending_trigger_count": 0,
        "manual_trigger_claimed": True,
        "locked_by": "recovery-worker",
        "locked_at": 456,
    }
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    recovered = await db.claim_due_schedule("recovery-worker", lock_grace_seconds=300)

    assert recovered is not None and recovered["manual_trigger_claimed"] is True
    query, update = collection.find_one_and_update.call_args.args[:2]
    assert query["manual_trigger_claimed"] is True
    assert "$inc" not in update

    collection.update_one.return_value = MagicMock(matched_count=1)
    assert await db.release_schedule("sched-1", worker_id="recovery-worker", locked_at=456) is True
    release_query, release_update = collection.update_one.call_args.args
    assert release_query == {"id": "sched-1", "locked_by": "recovery-worker", "locked_at": 456}
    assert release_update["$set"]["manual_trigger_claimed"] is False
    assert "next_run_at" not in release_update["$set"]


@pytest.mark.asyncio
async def test_async_mongo_renews_only_the_exact_claim_fence(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    collection.find_one_and_update.return_value = {"id": "sched-1"}
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))
    monkeypatch.setattr("agno.db.mongo.async_mongo.time.time", lambda: 123)

    renewed_at = await db.renew_schedule_claim("sched-1", worker_id="worker-1", locked_at=123)

    assert renewed_at == 124
    query, update = collection.find_one_and_update.call_args.args
    assert query == {"id": "sched-1", "locked_by": "worker-1", "locked_at": 123}
    assert update["$set"]["locked_at"] == renewed_at
    assert "manual_trigger_claimed" not in update["$set"]
    assert "pending_trigger_count" not in update["$set"]
    collection.update_one.side_effect = [MagicMock(matched_count=0), MagicMock(matched_count=1)]
    assert not await db.release_schedule("sched-1", worker_id="worker-1", locked_at=123)
    assert await db.release_schedule("sched-1", worker_id="worker-1", locked_at=renewed_at)


@pytest.mark.asyncio
async def test_async_mongo_release_schedule_unlocks_and_returns_true(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    update_result = MagicMock()
    update_result.matched_count = 1
    collection.update_one.return_value = update_result
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    released = await db.release_schedule("sched-1", next_run_at=999)

    assert released is True
    collection.update_one.assert_called_once()


@pytest.mark.asyncio
async def test_async_mongo_create_schedule_run_inserts_and_returns_data(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    run_data = {"id": "run-1", "schedule_id": "sched-1", "status": "running"}
    result = await db.create_schedule_run(run_data)

    collection.insert_one.assert_called_once_with(run_data)
    assert result == run_data


@pytest.mark.asyncio
async def test_async_mongo_update_schedule_run_updates_and_returns_run(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = AsyncMock()
    update_result = MagicMock()
    update_result.matched_count = 1
    collection.update_one.return_value = update_result
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))
    monkeypatch.setattr(db, "get_schedule_run", AsyncMock(return_value={"id": "run-1", "status": "success"}))

    result = await db.update_schedule_run("run-1", status="success")

    assert result == {"id": "run-1", "status": "success"}
    collection.update_one.assert_called_once()


@pytest.mark.asyncio
async def test_async_mongo_get_schedule_runs_returns_paginated_items_and_total(monkeypatch: pytest.MonkeyPatch):
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = MagicMock()
    collection.count_documents = AsyncMock(return_value=2)

    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(
        return_value=[
            {"_id": "mongo-1", "id": "run-1", "schedule_id": "sched-1"},
            {"_id": "mongo-2", "id": "run-2", "schedule_id": "sched-1"},
        ]
    )
    collection.find.return_value = cursor
    monkeypatch.setattr(db, "_get_collection", AsyncMock(return_value=collection))

    runs, total = await db.get_schedule_runs("sched-1", limit=20, page=1)

    assert total == 2
    assert runs == [
        {"id": "run-1", "schedule_id": "sched-1"},
        {"id": "run-2", "schedule_id": "sched-1"},
    ]
