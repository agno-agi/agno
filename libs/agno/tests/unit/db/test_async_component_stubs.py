"""Async adapters must refuse component-catalog calls loudly and uniformly.

Catalog v2 is sync-only; the async adapters' contract is a typed
NotImplementedError on every component method — never an AttributeError
(which reads as a bug, not a boundary) and never an async stub (calling an
async def without await returns an un-awaited coroutine and silently
no-ops at the real call sites, e.g. workflow.py's db.get_config).
"""

import inspect

import pytest

from agno.db.base import ComponentType

COMPONENT_METHOD_CALLS = {
    "get_component": {"component_id": "c1"},
    "get_components": {"component_ids": ["c1"]},
    "upsert_component": {"component_id": "c1"},
    "delete_component": {"component_id": "c1"},
    "restore_component": {"component_id": "c1"},
    "list_components": {},
    "create_component_with_config": {
        "component_id": "c1",
        "component_type": ComponentType.AGENT,
        "name": "c1",
        "config": {"name": "c1"},
    },
    "get_config": {"component_id": "c1"},
    "get_current_config": {"component_id": "c1"},
    "get_latest_config": {"component_id": "c1"},
    "get_latest_configs": {"component_ids": ["c1"]},
    "upsert_config": {"component_id": "c1"},
    "delete_config": {"component_id": "c1", "version": 1},
    "list_configs": {"component_id": "c1"},
    "set_current_version": {"component_id": "c1", "version": 1},
    "get_links": {"component_id": "c1", "version": 1},
    "get_dependents": {"component_id": "c1"},
    "load_component_graph": {"component_id": "c1"},
}


@pytest.fixture(params=["async_sqlite", "async_postgres", "async_mongo"])
def async_db(request, tmp_path):
    """Adapter instances built without touching any service."""
    if request.param == "async_sqlite":
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        return AsyncSqliteDb(db_file=str(tmp_path / "stub.db"))
    if request.param == "async_postgres":
        from agno.db.postgres.async_postgres import AsyncPostgresDb

        return AsyncPostgresDb(db_url="postgresql+psycopg_async://ai:ai@localhost:5532/ai")
    from agno.db.mongo.async_mongo import AsyncMongoDb

    return AsyncMongoDb(db_url="mongodb://mongoadmin:secret@localhost:27017", db_name="stub_probe")


@pytest.mark.parametrize("method_name", sorted(COMPONENT_METHOD_CALLS))
def test_component_method_raises_not_implemented(async_db, method_name):
    method = getattr(async_db, method_name, None)
    assert method is not None, f"{type(async_db).__name__}.{method_name} is missing entirely (AttributeError surface)"
    assert not inspect.iscoroutinefunction(method), (
        f"{type(async_db).__name__}.{method_name} is async def: called without await it returns "
        "an un-awaited coroutine and silently no-ops instead of raising"
    )
    with pytest.raises(NotImplementedError):
        method(**COMPONENT_METHOD_CALLS[method_name])
