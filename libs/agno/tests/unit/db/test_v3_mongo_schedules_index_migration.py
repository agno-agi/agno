"""Tests for the Mongo schedules index migration (v3_0_0) and the per-index bootstrap.

Pre-3.0.0 shipped a global-unique ``name`` index on the schedules collection.
v3 names are unique per owner, so on legacy collections that index must be
dropped, and one conflicting index must not prevent the rest of the v3 index
set (``user_id`` and the compound claim/list indexes) from being created.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("pymongo", reason="pymongo not installed")

from pymongo.errors import ConnectionFailure, OperationFailure  # noqa: E402

from agno.db.migrations.versions.v3_0_0 import _migrate_async_mongo, _migrate_mongo, _revert_mongo  # noqa: E402
from agno.db.mongo.schemas import get_collection_indexes  # noqa: E402
from agno.db.mongo.utils import create_collection_indexes, create_collection_indexes_async  # noqa: E402

# create_collection_indexes is mocked in these tests, so the fixtures already
# include the unique (user_id, name) backstop the real rebuild would add — the
# migration's post-check confirms it is present.
LEGACY_INDEXES = {
    "_id_": {"key": [("_id", 1)]},
    "id_1": {"key": [("id", 1)], "unique": True},
    "name_1": {"key": [("name", 1)], "unique": True},
    "uq_user_name": {"key": [("user_id", 1), ("name", 1)], "unique": True},
}

V3_INDEXES = {
    "_id_": {"key": [("_id", 1)]},
    "id_1": {"key": [("id", 1)], "unique": True},
    "name_1": {"key": [("name", 1)]},
    "user_id_1": {"key": [("user_id", 1)]},
    "uq_user_name": {"key": [("user_id", 1), ("name", 1)], "unique": True},
}


def _mock_db(collection, collection_names=("agno_schedules",)):
    db = MagicMock()
    db.database.list_collection_names.return_value = list(collection_names)
    db.database.__getitem__.return_value = collection
    return db


def _mock_async_db(collection, collection_names=("agno_schedules",)):
    db = MagicMock()
    db.database.list_collection_names = AsyncMock(return_value=list(collection_names))
    db.database.__getitem__.return_value = collection
    return db


class TestPerIndexBootstrap:
    def test_one_conflicting_index_does_not_starve_the_rest(self):
        collection = MagicMock()
        collection.create_index.side_effect = [
            None,
            OperationFailure("IndexOptionsConflict", code=85),
            *([None] * 20),
        ]

        create_collection_indexes(collection, "schedules")

        assert collection.create_index.call_count == len(get_collection_indexes("schedules"))

    def test_connection_failure_aborts_instead_of_timing_out_per_index(self):
        collection = MagicMock()
        collection.create_index.side_effect = [None, ConnectionFailure("server selection timed out")]

        create_collection_indexes(collection, "schedules")

        assert collection.create_index.call_count == 2

    @pytest.mark.asyncio
    async def test_async_one_conflicting_index_does_not_starve_the_rest(self):
        collection = MagicMock()
        collection.create_index = AsyncMock(
            side_effect=[None, OperationFailure("IndexOptionsConflict", code=85), *([None] * 20)]
        )

        await create_collection_indexes_async(collection, "schedules")

        assert collection.create_index.call_count == len(get_collection_indexes("schedules"))

    @pytest.mark.asyncio
    async def test_async_connection_failure_aborts_instead_of_timing_out_per_index(self):
        collection = MagicMock()
        collection.create_index = AsyncMock(side_effect=[None, ConnectionFailure("server selection timed out")])

        await create_collection_indexes_async(collection, "schedules")

        assert collection.create_index.call_count == 2


class TestMigrateSchedulesIndexes:
    def test_drops_legacy_unique_name_index_and_rebuilds(self):
        collection = MagicMock()
        collection.index_information.return_value = dict(LEGACY_INDEXES)

        assert _migrate_mongo(_mock_db(collection), "schedules", "agno_schedules") is True

        collection.drop_index.assert_called_once_with("name_1")
        assert collection.create_index.call_count == len(get_collection_indexes("schedules"))

    def test_noop_on_already_v3_collection(self):
        collection = MagicMock()
        collection.index_information.return_value = dict(V3_INDEXES)

        assert _migrate_mongo(_mock_db(collection), "schedules", "agno_schedules") is True

        collection.drop_index.assert_not_called()

    def test_skips_missing_collection(self):
        collection = MagicMock()

        assert _migrate_mongo(_mock_db(collection, collection_names=()), "schedules", "agno_schedules") is False

        collection.index_information.assert_not_called()

    def test_raises_when_backstop_cannot_be_built_over_duplicates(self):
        # create_collection_indexes tolerates a per-index DuplicateKey failure, so if the
        # backstop is absent afterward the migration must RAISE (not stamp) — otherwise the
        # version advances and the index can never be created on a re-run.
        from agno.db.migrations.versions.v3_0_0 import ScheduleDuplicateNamesError

        collection = MagicMock()
        # Post-rebuild state is missing uq_user_name (blocked by duplicates).
        collection.index_information.return_value = {
            "_id_": {"key": [("_id", 1)]},
            "name_1": {"key": [("name", 1)]},
        }
        with pytest.raises(ScheduleDuplicateNamesError, match="[Rr]esolve the duplicates"):
            _migrate_mongo(_mock_db(collection), "schedules", "agno_schedules")

    def test_unique_id_index_is_not_touched(self):
        collection = MagicMock()
        collection.index_information.return_value = dict(LEGACY_INDEXES)

        _migrate_mongo(_mock_db(collection), "schedules", "agno_schedules")

        dropped = {call.args[0] for call in collection.drop_index.call_args_list}
        assert dropped == {"name_1"}

    @pytest.mark.asyncio
    async def test_async_drops_legacy_unique_name_index_and_rebuilds(self):
        collection = MagicMock()
        collection.index_information = AsyncMock(return_value=dict(LEGACY_INDEXES))
        collection.drop_index = AsyncMock()
        collection.create_index = AsyncMock()

        assert await _migrate_async_mongo(_mock_async_db(collection), "schedules", "agno_schedules") is True

        collection.drop_index.assert_called_once_with("name_1")
        assert collection.create_index.call_count == len(get_collection_indexes("schedules"))


class TestRevertSchedulesIndexes:
    def test_restores_v2_unique_name_index(self):
        collection = MagicMock()
        collection.index_information.return_value = dict(V3_INDEXES)

        assert _revert_mongo(_mock_db(collection), "schedules", "agno_schedules") is True

        collection.drop_index.assert_called_once_with("name_1")
        collection.create_index.assert_called_once_with([("name", 1)], unique=True)

    def test_survives_duplicate_names_on_restore(self):
        collection = MagicMock()
        collection.index_information.return_value = dict(V3_INDEXES)
        collection.create_index.side_effect = Exception("E11000 duplicate key")

        assert _revert_mongo(_mock_db(collection), "schedules", "agno_schedules") is True
