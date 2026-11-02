import asyncio
from datetime import date
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from pymongo import AsyncMongoClient

from agno.db.base import SessionType
from agno.db.mongo import AsyncMongoDb
from agno.db.utils import METRICS_REFRESH_ID
from agno.session import AgentSession


def test_id_is_deterministic():
    """Test that two db instances with same URL have same ID"""
    db1 = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    db2 = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    assert db1.id == db2.id


def test_id_different_for_different_configs():
    """Test that different configs produce different IDs"""
    db1 = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db1")
    db2 = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db2")

    assert db1.id != db2.id


def test_init_with_url():
    """Test initialization with database URL"""
    db = AsyncMongoDb(
        db_url="mongodb://localhost:27017",
        db_name="test_db",
        session_collection="sessions",
        memory_collection="memories",
    )

    assert db.db_url == "mongodb://localhost:27017"
    assert db.db_name == "test_db"
    assert db.session_table_name == "sessions"
    assert db.memory_table_name == "memories"


def test_init_with_client():
    """Test initialization with provided client"""
    test_client = AsyncMongoClient()
    db = AsyncMongoDb(db_client=test_client, db_name="test_db", session_collection="sessions")

    assert db._provided_client == test_client
    assert db.db_name == "test_db"
    assert db.session_table_name == "sessions"


def test_init_no_url_or_client():
    """Test initialization fails without URL or client"""
    with pytest.raises(ValueError, match="One of db_url or db_client must be provided"):
        AsyncMongoDb(db_name="test_db")


def test_init_defaults():
    """Test initialization with defaults"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017")

    assert db.db_name == "agno"
    assert db._client is None
    assert db._database is None
    assert db._event_loop is None


def test_init_with_all_collections():
    """Test initialization with all collection names"""
    db = AsyncMongoDb(
        db_url="mongodb://localhost:27017",
        db_name="test_db",
        session_collection="sessions",
        memory_collection="memories",
        metrics_collection="metrics",
        eval_collection="evals",
        knowledge_collection="knowledge",
    )

    assert db.session_table_name == "sessions"
    assert db.memory_table_name == "memories"
    assert db.metrics_table_name == "metrics"
    assert db.eval_table_name == "evals"
    assert db.knowledge_table_name == "knowledge"


@pytest.mark.asyncio
@patch.object(AsyncMongoDb, "table_exists", new=AsyncMock(return_value=True))
async def test_initialization_flags_cleared_on_event_loop_change():
    """Test that _initialized flags are cleared when event loop changes.

    This is the primary fix for the bug. When the event loop changes,
    both collection caches AND initialization flags must be cleared.

    Bug context: After upgrading from 2.2.7 to 2.2.9, users experienced
    "Event loop is closed" errors when calling aupsert_session in custom
    situations with subagents, particularly when multiple asyncio.run()
    calls were made.
    """
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_event_loop_fix")

    # First operation - create collections
    await db._get_collection("sessions", create_collection_if_not_found=True)
    await db._get_collection("memories", create_collection_if_not_found=True)

    # Should have collections cached
    assert hasattr(db, "session_collection")
    assert hasattr(db, "memory_collection")

    # Should have initialized flags
    initialized_flags_before = [attr for attr in vars(db).keys() if attr.endswith("_initialized")]
    assert len(initialized_flags_before) >= 2, "Should have initialized flags"

    # Close old client before simulating event loop change
    await db.close()

    # Manually simulate event loop change (what _ensure_client does)
    db._event_loop = None  # Force it to detect a "new" loop next time
    _ = db.db_client  # This should trigger cleanup

    # After loop change, collections AND initialized flags should be cleared
    assert not hasattr(db, "session_collection"), "session_collection should be cleared"
    assert not hasattr(db, "memory_collection"), "memory_collection should be cleared"

    # Check that ALL _initialized flags are cleared (this is the fix!)
    initialized_flags_after = [attr for attr in vars(db).keys() if attr.endswith("_initialized")]
    assert len(initialized_flags_after) == 0, (
        f"All _initialized flags should be cleared, but found: {initialized_flags_after}"
    )

    await db.close()


@pytest.mark.asyncio
@patch.object(AsyncMongoDb, "table_exists", new=AsyncMock(return_value=True))
async def test_indexes_awaited_properly():
    """Test that index creation is properly awaited.

    The second part of the fix ensures create_collection_indexes_async
    properly awaits Motor's async create_index() calls, preventing
    unawaited futures from being left on the event loop.
    """
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_await_indexes")

    # This should complete without hanging or leaving pending futures
    collection = await db._get_collection("sessions", create_collection_if_not_found=True)
    assert collection is not None

    # Verify no pending tasks from our code (exclude current task and PyMongo/Motor internals)
    current_task = asyncio.current_task()

    def _is_pymongo_internal(task: asyncio.Task) -> bool:
        """Check if a task belongs to PyMongo/Motor internals."""
        coro = task.get_coro()
        code_file = getattr(getattr(coro, "cr_code", None), "co_filename", "")
        return "pymongo" in code_file or "motor" in code_file

    pending = [
        task
        for task in asyncio.all_tasks()
        if not task.done() and task != current_task and not _is_pymongo_internal(task)
    ]

    assert len(pending) == 0, f"Should have no pending tasks, but found: {pending}"

    await db.close()


@pytest.mark.asyncio
@patch.object(AsyncMongoDb, "table_exists", new=AsyncMock(return_value=True))
async def test_collection_cache_reset_on_event_loop_change():
    """Test that all collection caches are reset on event loop change"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_cache_reset")

    # Create collections
    await db._get_collection("sessions", create_collection_if_not_found=True)
    await db._get_collection("memories", create_collection_if_not_found=True)
    await db._get_collection("metrics", create_collection_if_not_found=True)

    # Should have multiple collections cached
    collections_before = [attr for attr in vars(db).keys() if attr.endswith("_collection")]
    assert len(collections_before) >= 3

    # Close the current client before simulating event loop change
    await db.close()

    # Force event loop change
    db._event_loop = None
    _ = db.db_client

    # All collections should be cleared
    collections_after = [attr for attr in vars(db).keys() if attr.endswith("_collection")]
    assert len(collections_after) == 0, f"All collections should be cleared, found: {collections_after}"

    await db.close()


@pytest.mark.asyncio
async def test_get_collection_invalid_type():
    """Test getting collection with invalid type raises error"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_invalid_type")

    with pytest.raises(ValueError, match="Unknown table type"):
        await db._get_collection("invalid_type")


@pytest.mark.asyncio
async def test_get_collection_without_table_name():
    """Test that _get_collection raises error if table name not configured"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_no_table_name")

    # Manually clear the table name to simulate not being configured
    db.session_table_name = None  # type: ignore

    with pytest.raises(ValueError, match="Session collection was not provided"):
        await db._get_collection("sessions", create_collection_if_not_found=True)


@pytest.mark.asyncio
async def test_created_sessions_collection_stores_latest_schema_version():
    """A sessions collection the store creates stores the latest schema version, so metrics never read its legacy runs."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    with (
        patch.object(db, "table_exists", AsyncMock(return_value=False)),
        patch.object(db, "upsert_schema_version", AsyncMock()) as upsert_schema_version,
        patch("agno.db.mongo.async_mongo.create_collection_indexes_async", AsyncMock()),
    ):
        await db._get_collection("sessions", create_collection_if_not_found=True)

    upsert_schema_version.assert_awaited_once_with(table_name=db.session_table_name, version="3.0.0")


def test_db_client_property():
    """Test db_client property calls _ensure_client"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_client_property")

    with patch.object(db, "_ensure_client", return_value=Mock()) as mock_ensure:
        client = db.db_client
        assert client is not None
        mock_ensure.assert_called_once()


def test_should_reset_collection_cache():
    """Test _should_reset_collection_cache method"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_should_reset")

    # Before any event loop is set
    assert db._should_reset_collection_cache() is False

    # After setting event loop
    loop = asyncio.new_event_loop()
    try:
        db._event_loop = loop
        asyncio.set_event_loop(loop)
        # Should return False when same loop
        assert db._should_reset_collection_cache() is False
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_client_type_constants():
    """Test that client type constants are defined correctly"""
    assert AsyncMongoDb.CLIENT_TYPE_MOTOR == "motor"
    assert AsyncMongoDb.CLIENT_TYPE_PYMONGO_ASYNC == "pymongo_async"
    assert AsyncMongoDb.CLIENT_TYPE_UNKNOWN == "unknown"


def test_detect_motor_client_type():
    """Test that Motor client is correctly detected"""
    try:
        from motor.motor_asyncio import AsyncIOMotorClient

        mock_client = Mock(spec=AsyncIOMotorClient)
        db = AsyncMongoDb(db_client=mock_client, db_name="test_db")
        assert db._client_type == AsyncMongoDb.CLIENT_TYPE_MOTOR
    except ImportError:
        pytest.skip("Motor not available")


def test_detect_pymongo_async_client_type():
    """Test that PyMongo async client is correctly detected"""
    # Check if PyMongo async is available
    try:
        import pymongo  # noqa: F401

        # Verify AsyncMongoClient exists
        if not hasattr(pymongo, "AsyncMongoClient"):
            pytest.skip("PyMongo async not available")
    except ImportError:
        pytest.skip("PyMongo async not available")

    # Create a mock that will pass isinstance check
    # We need to make the mock actually be an instance of AsyncMongoClient
    # or use a real instance if possible, or patch the detection
    mock_client = Mock()
    # Set the class name and module to help with fallback detection
    mock_client.__class__.__name__ = "AsyncMongoClient"
    mock_client.__class__.__module__ = "pymongo"
    db = AsyncMongoDb(db_client=mock_client, db_name="test_db")
    assert db._client_type == AsyncMongoDb.CLIENT_TYPE_PYMONGO_ASYNC


def test_auto_select_preferred_client_from_url():
    """Test that preferred client is auto-selected when creating from URL"""
    # Import availability flags from the module
    from agno.db.mongo.async_mongo import MOTOR_AVAILABLE, PYMONGO_ASYNC_AVAILABLE

    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    # Should prefer PyMongo async if available, else Motor
    if PYMONGO_ASYNC_AVAILABLE:
        assert db._client_type == AsyncMongoDb.CLIENT_TYPE_PYMONGO_ASYNC
    elif MOTOR_AVAILABLE:
        assert db._client_type == AsyncMongoDb.CLIENT_TYPE_MOTOR
    else:
        pytest.fail("Neither client type available")


@pytest.mark.asyncio
async def test_get_session_query_does_not_include_session_type():
    """Test that get_session queries only by session_id (and user_id), not session_type.

    This ensures consistency with all other database implementations where
    session_type is used only for deserialization, not as a query filter.
    """
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    mock_collection = AsyncMock()
    mock_collection.find_one.return_value = None

    with patch.object(db, "_get_collection", return_value=mock_collection):
        result = await db.get_session(
            session_id="test-session-id",
            session_type=SessionType.AGENT,
            user_id="test-user",
        )

    assert result is None
    mock_collection.find_one.assert_called_once_with({"session_id": "test-session-id", "user_id": "test-user"})


@pytest.mark.asyncio
async def test_get_session_query_without_user_id():
    """Test that get_session omits user_id from query when not provided."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    mock_collection = AsyncMock()
    mock_collection.find_one.return_value = None

    with patch.object(db, "_get_collection", return_value=mock_collection):
        result = await db.get_session(
            session_id="test-session-id",
            session_type=SessionType.TEAM,
        )

    assert result is None
    mock_collection.find_one.assert_called_once_with({"session_id": "test-session-id"})


@pytest.mark.asyncio
async def test_get_collection_refetches_when_cached_none():
    """Regression: a read with create_collection_if_not_found=False on a not-yet-created
    collection must NOT cache None. Otherwise a GET before the first write would poison the
    cache and every later write would be silently dropped (reproduced on the learnings path:
    GET then POST saved nothing; POST first worked)."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_none_cache", learnings_collection="learnings")
    sentinel = object()
    db._should_reset_collection_cache = Mock(return_value=False)
    db._get_or_create_collection = AsyncMock(side_effect=[None, sentinel])

    # Stub the client property so nothing tries to connect.
    with patch.object(type(db), "db_client", new_callable=PropertyMock, return_value=Mock()):
        # 1) Read on a missing collection -> None, and must not be cached.
        first = await db._get_collection("learnings", create_collection_if_not_found=False)
        assert first is None

        # 2) A subsequent write must re-fetch (and actually get the collection), not the cached None.
        second = await db._get_collection("learnings", create_collection_if_not_found=True)

    assert second is sentinel
    assert db._get_or_create_collection.await_count == 2


@pytest.mark.asyncio
async def test_text_filters_match_literal_text():
    """session_name and search_content are user text, not regex patterns."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    cursor = Mock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    mock_collection = Mock()
    mock_collection.find.return_value = cursor
    mock_collection.count_documents = AsyncMock(return_value=0)

    with patch.object(db, "_get_collection", AsyncMock(return_value=mock_collection)):
        await db.get_sessions(session_name="v1.2(draft", deserialize=False)
        await db.get_user_memories(search_content="v1.2(draft", deserialize=False)

    sessions_query, memories_query = [c.args[0] for c in mock_collection.count_documents.call_args_list]
    assert sessions_query["session_data.session_name"] == {"$regex": r"v1\.2\(draft", "$options": "i"}
    assert memories_query["memory"] == {"$regex": r"v1\.2\(draft", "$options": "i"}


@pytest.mark.asyncio
async def test_metrics_legacy_runs_stop_when_refresh_taken_over():
    """The legacy runs are read with a heartbeat per batch, and stop once another process took the refresh over."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    cursor = Mock()
    cursor.batch_size.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[{"session_id": "s1", "created_at": 0, "runs": [{"run_id": "r1"}]}])
    sessions_collection = Mock()
    sessions_collection.find.return_value = cursor

    with patch.object(db, "_heartbeat_metrics_refresh", AsyncMock(return_value=False)) as heartbeat:
        result = await db._get_metrics_legacy_runs(sessions_collection, None, 0, 86400, Mock(), "worker")

    assert result is None
    heartbeat.assert_awaited_once()
    cursor.to_list.assert_awaited_once()


@pytest.mark.asyncio
async def test_metrics_release_keeps_rebuild_mark_after_claim_of_none():
    """A claim of no fingerprint still compares, so a rebuild marked after it is kept."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    refreshes_collection = Mock()
    refreshes_collection.update_one = AsyncMock()

    await db._release_metrics_refresh(refreshes_collection, "worker", fingerprint=["2026-11-01", 1, 2])

    values = refreshes_collection.update_one.call_args.args[1][0]["$set"]
    assert values["fingerprint"]["$cond"][0] == {"$eq": [{"$ifNull": ["$fingerprint", None]}, {"$literal": None}]}
    assert values["fingerprint"]["$cond"][2] == "$fingerprint"


@pytest.mark.asyncio
async def test_metrics_rebuild_reopen_failure_marks_refresh_failed():
    """A rebuild whose reopen fails shows the error in the refresh status, unless a process holds the refresh or a
    calculation started or finished after the rebuild read it."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    refreshes_collection = Mock()
    refreshes_collection.find_one = AsyncMock(
        return_value={"id": METRICS_REFRESH_ID, "started_at": 100, "finished_at": 200}
    )
    refreshes_collection.update_one = AsyncMock()

    with (
        patch.object(db, "_get_collection", AsyncMock(return_value=refreshes_collection)),
        patch("agno.db.mongo.async_mongo.areopen_metrics_days_from", AsyncMock(side_effect=Exception("reopen failed"))),
    ):
        with pytest.raises(Exception, match="reopen failed"):
            await db.calculate_metrics_dates(rebuild_from=date(2026, 10, 1))

    query, pipeline = refreshes_collection.update_one.call_args.args
    assert query == {"id": METRICS_REFRESH_ID, "locked_by": None, "started_at": 100, "finished_at": 200}
    assert pipeline[0]["$set"]["status"] == "failed"


@pytest.mark.asyncio
async def test_upsert_sessions_reads_back_in_chunks():
    """The sessions written are read back a chunk of ids at a time, so many long ids never exceed a query document."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")

    async def _docs(docs):
        for doc in docs:
            yield doc

    collection = Mock()
    collection.bulk_write = AsyncMock()
    # The lookup before the write passes a projection and finds nothing stored
    collection.find.side_effect = lambda query, *args: _docs(
        [] if args else [{"session_id": sid, "session_type": "agent"} for sid in query["session_id"]["$in"]]
    )

    with (
        patch.object(db, "_get_collection", AsyncMock(return_value=collection)),
        patch.object(db, "_reopen_metrics_days", AsyncMock()),
        patch("agno.db.mongo.async_mongo.METRICS_IN_LIST_LIMIT", 1),
    ):
        results = await db.upsert_sessions([AgentSession(session_id="s1"), AgentSession(session_id="s2")])

    assert [session.session_id for session in results] == ["s1", "s2"]
    read_backs = [call.args[0] for call in collection.find.call_args_list if len(call.args) == 1]
    assert read_backs == [{"session_id": {"$in": ["s1"]}}, {"session_id": {"$in": ["s2"]}}]


@pytest.mark.asyncio
async def test_an_unstamped_sessions_collection_with_no_legacy_runs_is_read_for_them_once():
    """A sessions collection stamped with no version, as 3.0 and 3.1 left it, is read for legacy runs once, and not
    again once that read of every session found none."""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    legacy_reads = AsyncMock(return_value=({}, {}))

    with (
        patch.object(db, "_get_collection", AsyncMock(return_value=Mock())),
        patch.object(db, "get_latest_schema_version", AsyncMock(return_value="2.0.0")),
        patch.object(db, "_claim_metrics_refresh", AsyncMock(return_value={"finished_at": 1, "fingerprint": None})),
        patch.object(db, "_get_metrics_dates_to_calculate", AsyncMock(return_value=([date(2026, 10, 1)], None))),
        patch.object(db, "_get_metrics_legacy_runs", legacy_reads),
        patch.object(db, "_heartbeat_metrics_refresh", AsyncMock(return_value=True)),
        patch.object(db, "_calculate_date_metrics", AsyncMock(return_value=True)),
        patch.object(db, "_get_open_metrics_months", AsyncMock(return_value=[])),
        patch.object(db, "_calculate_month_metrics", AsyncMock(return_value=True)),
        patch.object(db, "_release_metrics_refresh", AsyncMock()),
    ):
        assert await db.calculate_metrics_dates() == [date(2026, 10, 1)]
        assert await db.calculate_metrics_dates() == [date(2026, 10, 1)]

    # The one read starts at 0, so it read every session
    assert [read.args[2] for read in legacy_reads.call_args_list] == [0]
