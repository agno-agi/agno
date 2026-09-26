"""Every DB backend must default to descending order when sort_order is omitted.

tests/unit/os/routers/test_sort_order_default.py fixes the intended default at the
router layer: an omitted sort_order reaches the DB as SortOrder.DESC. The DB classes
are also public API and are called directly, where sort_order is simply None. These
tests hold every backend's apply_sorting to the same default so a "most recent first"
listing does not silently invert when the backend changes.

Backends whose client library is not part of the [dev] extra are skipped rather than
stubbed, matching how the rest of this directory handles optional dependencies.
"""

from typing import Any, Dict, List

import pytest

# Ordered oldest to newest, so natural insertion order is the ascending order.
RECORDS: List[Dict[str, Any]] = [
    {"session_id": "oldest", "created_at": 100, "updated_at": 100},
    {"session_id": "middle", "created_at": 200, "updated_at": 200},
    {"session_id": "newest", "created_at": 300, "updated_at": 300},
]

NEWEST_FIRST = ["newest", "middle", "oldest"]
OLDEST_FIRST = ["oldest", "middle", "newest"]

# Backends that sort an already-materialized list of records in Python.
LIST_SORTERS = [
    ("in_memory", "agno.db.in_memory.utils", "apply_sorting"),
    ("json", "agno.db.json.utils", "apply_sorting"),
    ("gcs_json", "agno.db.gcs_json.utils", "apply_sorting"),
    ("redis", "agno.db.redis.utils", "apply_sorting"),
    ("valkey", "agno.db.valkey.utils", "apply_sorting"),
    ("dynamo", "agno.db.dynamo.utils", "apply_sorting"),
    ("firestore", "agno.db.firestore.utils", "apply_sorting_to_records"),
]

# Backends that push ORDER BY down to SQLAlchemy.
SQL_BACKENDS = ["sqlite", "postgres", "mysql", "singlestore"]


def _sorter(module: str, func: str):
    return getattr(pytest.importorskip(module), func)


def _ids(records: List[Dict[str, Any]]) -> List[str]:
    return [record["session_id"] for record in records]


@pytest.mark.parametrize("name,module,func", LIST_SORTERS)
def test_omitted_sort_order_is_descending(name: str, module: str, func: str):
    """An omitted sort_order must mean newest first, as it does at the router layer."""
    apply_sorting = _sorter(module, func)

    assert _ids(apply_sorting(list(RECORDS), sort_by="created_at", sort_order=None)) == NEWEST_FIRST


@pytest.mark.parametrize("name,module,func", LIST_SORTERS)
def test_explicit_sort_order_is_unchanged(name: str, module: str, func: str):
    """The explicit directions keep working; only the omitted case moves."""
    apply_sorting = _sorter(module, func)

    assert _ids(apply_sorting(list(RECORDS), sort_by="created_at", sort_order="desc")) == NEWEST_FIRST
    assert _ids(apply_sorting(list(RECORDS), sort_by="created_at", sort_order="asc")) == OLDEST_FIRST


@pytest.mark.parametrize("name,module,func", LIST_SORTERS)
def test_updated_at_falls_back_to_created_at(name: str, module: str, func: str):
    """The documented pre-2.0 fallback still holds under the default direction."""
    apply_sorting = _sorter(module, func)
    records = [
        {"session_id": "oldest", "created_at": 100, "updated_at": None},
        {"session_id": "newest", "created_at": 300, "updated_at": None},
    ]

    # Both rows resolve to their created_at, so the newer creation time leads.
    assert _ids(apply_sorting(records, sort_by="updated_at", sort_order=None))[0] == "newest"


def test_dynamo_defaults_to_created_at_descending():
    """Dynamo substitutes created_at for a missing sort_by, so it always sorts."""
    apply_sorting = _sorter("agno.db.dynamo.utils", "apply_sorting")

    assert _ids(apply_sorting(list(RECORDS), sort_by=None, sort_order=None)) == NEWEST_FIRST


@pytest.mark.parametrize("backend", SQL_BACKENDS)
def test_sql_backends_order_by_desc_when_sort_order_omitted(backend: str):
    """The SQL backends already default to DESC; hold them there."""
    sqlalchemy = pytest.importorskip("sqlalchemy")
    apply_sorting = _sorter(f"agno.db.{backend}.utils", "apply_sorting")

    metadata = sqlalchemy.MetaData()
    table = sqlalchemy.Table(
        "sessions",
        metadata,
        sqlalchemy.Column("session_id", sqlalchemy.String),
        sqlalchemy.Column("created_at", sqlalchemy.Integer),
        sqlalchemy.Column("updated_at", sqlalchemy.Integer),
    )

    statement = str(apply_sorting(sqlalchemy.select(table), table, sort_by="created_at", sort_order=None))

    assert "ORDER BY" in statement.upper()
    assert "DESC" in statement.upper()


def test_mongo_sort_spec_is_descending_when_sort_order_omitted():
    """Mongo pushes sorting to the driver; -1 is descending."""
    apply_sorting = _sorter("agno.db.mongo.utils", "apply_sorting")

    assert apply_sorting({}, sort_by="created_at", sort_order=None) == [("created_at", -1)]
