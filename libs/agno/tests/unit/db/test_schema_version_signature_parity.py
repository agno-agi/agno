"""Regression tests for reviewer comment #4 on PR #8350.

The ``BaseDb`` abstract contract declares::

    def get_latest_schema_version(self, table_name: str)
    def upsert_schema_version(self, table_name: str, version: str)

but eight adapters (json, gcs_json, in_memory, mongo (sync+async), redis,
firestore, dynamo, surrealdb) previously overrode these with no-arg
signatures. ``MigrationManager.up()`` / ``down()`` calls the methods
positionally with ``table_name``, so any of those adapters crashed with::

    TypeError: X.get_latest_schema_version() takes 1 positional argument but 2 were given

This test asserts every listed adapter now matches the base signature so
migrations run without a hard crash. It also verifies
``MigrationManager.up()`` end-to-end against a real ``JsonDb`` (the reviewer's
exact example) — before the fix it crashed on the first table.
"""

from __future__ import annotations

import asyncio
import inspect
import tempfile
from typing import Any, Callable

import pytest

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.migrations.manager import MigrationManager

# ---------------------------------------------------------------------------
# Static signature checks — no DB drivers required for these
# ---------------------------------------------------------------------------

_ADAPTER_IMPORTS: list[tuple[str, str, str]] = [
    ("agno.db.json.json_db", "JsonDb", "sync"),
    ("agno.db.gcs_json.gcs_json_db", "GcsJsonDb", "sync"),
    ("agno.db.in_memory.in_memory_db", "InMemoryDb", "sync"),
    ("agno.db.mongo.mongo", "MongoDb", "sync"),
    ("agno.db.mongo.async_mongo", "AsyncMongoDb", "sync"),
    ("agno.db.redis.redis", "RedisDb", "sync"),
    ("agno.db.valkey.valkey", "ValkeyDb", "sync"),
    ("agno.db.firestore.firestore", "FirestoreDb", "sync"),
    ("agno.db.dynamo.dynamo", "DynamoDb", "sync"),
    ("agno.db.surrealdb.surrealdb", "SurrealDb", "sync"),
]


def _try_import_class(module_path: str, class_name: str):
    """Some adapters have optional native drivers (mongo, firestore, gcs,
    dynamo, surrealdb, redis). Skip cleanly if the driver isn't installed
    — the signature check is what we're after, not runtime behavior."""
    try:
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)
    except Exception as e:  # ImportError, or SDK-init failure at import time
        pytest.skip(f"skip {class_name}: driver unavailable ({type(e).__name__}: {e})")


def _accepts_arg(fn: Callable[..., Any], arg_name: str) -> bool:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return arg_name in sig.parameters


class TestGetLatestSchemaVersionAcceptsTableName:
    """Base contract: ``get_latest_schema_version(self, table_name: str)``.
    Each adapter's override must accept ``table_name`` — positionally *or*
    as a defaulted kwarg — so ``MigrationManager`` can call it uniformly."""

    @pytest.mark.parametrize("module_path,class_name,_mode", _ADAPTER_IMPORTS)
    def test_signature_accepts_table_name(self, module_path: str, class_name: str, _mode: str):
        cls = _try_import_class(module_path, class_name)
        assert _accepts_arg(cls.get_latest_schema_version, "table_name"), (
            f"{class_name}.get_latest_schema_version must accept a `table_name` argument "
            "— MigrationManager calls it positionally and will otherwise raise "
            "TypeError mid-migration."
        )


class TestUpsertSchemaVersionAcceptsTableName:
    """Base contract: ``upsert_schema_version(self, table_name: str, version: str)``.
    Same rationale as above — the manager calls this positionally after
    successful migrations to record the new version."""

    @pytest.mark.parametrize("module_path,class_name,_mode", _ADAPTER_IMPORTS)
    def test_signature_accepts_table_name(self, module_path: str, class_name: str, _mode: str):
        cls = _try_import_class(module_path, class_name)
        assert _accepts_arg(cls.upsert_schema_version, "table_name"), (
            f"{class_name}.upsert_schema_version must accept a `table_name` argument."
        )

    @pytest.mark.parametrize("module_path,class_name,_mode", _ADAPTER_IMPORTS)
    def test_signature_accepts_version(self, module_path: str, class_name: str, _mode: str):
        cls = _try_import_class(module_path, class_name)
        assert _accepts_arg(cls.upsert_schema_version, "version"), (
            f"{class_name}.upsert_schema_version must accept a `version` argument."
        )


# ---------------------------------------------------------------------------
# End-to-end reproduction of the reviewer's exact scenario
# ---------------------------------------------------------------------------


class TestJsonDbMigrationDoesNotCrash:
    """The reviewer flagged JsonDb explicitly. Before the fix, this call
    raised ``TypeError: get_latest_schema_version() takes 1 positional
    argument but 2 were given`` on the first iteration."""

    def test_migration_up_completes_without_typeerror(self):
        from agno.db.json.json_db import JsonDb

        with tempfile.TemporaryDirectory() as tmp:
            db = JsonDb(db_path=tmp)
            mgr = MigrationManager(db=db)

            # If any table crashes with TypeError, this raises and the test fails.
            # Cleanly skipping all tables (raw_version is None → skip) is the
            # expected outcome for a fresh JsonDb with no version records.
            asyncio.run(mgr.up(target_version="3.0.0"))

    def test_migration_down_completes_without_typeerror(self):
        from agno.db.json.json_db import JsonDb

        with tempfile.TemporaryDirectory() as tmp:
            db = JsonDb(db_path=tmp)
            mgr = MigrationManager(db=db)
            asyncio.run(mgr.down(target_version="2.0.0"))

    def test_get_and_upsert_can_be_called_with_table_name_positionally(self):
        """``MigrationManager`` calls both methods with ``table_name`` as the
        first positional arg. Verify the concrete JsonDb accepts that shape."""
        from agno.db.json.json_db import JsonDb

        with tempfile.TemporaryDirectory() as tmp:
            db = JsonDb(db_path=tmp)
            # Must not raise TypeError:
            db.get_latest_schema_version("some_table")
            db.upsert_schema_version("some_table", "3.0.0")


class TestBaseDbContractSatisfied:
    """Sanity: each adapter is still a concrete subclass of ``BaseDb`` or
    ``AsyncBaseDb`` (i.e. the abstract methods are still implemented — we
    haven't accidentally re-broken instantiability)."""

    @pytest.mark.parametrize("module_path,class_name,_mode", _ADAPTER_IMPORTS)
    def test_is_concrete_subclass(self, module_path: str, class_name: str, _mode: str):
        cls = _try_import_class(module_path, class_name)
        assert issubclass(cls, (BaseDb, AsyncBaseDb)), f"{class_name} must subclass BaseDb or AsyncBaseDb"
        # Not abstract: no unimplemented abstract methods
        assert not getattr(cls, "__abstractmethods__", frozenset()), (
            f"{class_name} still has unimplemented abstract methods: {cls.__abstractmethods__}"
        )
