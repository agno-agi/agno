"""Regression test for reviewer comment #12 on PR #8350.

Sibling SQL adapters (MySQL, Postgres) pass a custom ``json_serializer`` to
``create_engine`` so datetime/Decimal/etc values in JSON columns don't blow
up on insert. SingleStore was missing this. Insertions carrying non-JSON-
native types raised ``TypeError`` from ``json.dumps``.

We can't spin up a real SingleStore instance in unit tests, but we can
assert the wiring at the source: the module imports ``json_serializer``
from ``agno.db.utils`` and passes it to ``create_engine`` in ``__init__``.
"""

from __future__ import annotations

import inspect

import pytest


def _module_source() -> str:
    try:
        from agno.db.singlestore import singlestore as ss_mod
    except ImportError:
        pytest.skip("singlestore driver not installed")
    return inspect.getsource(ss_mod)


class TestSingleStoreJsonSerializerWired:
    def test_import_present(self):
        src = _module_source()
        assert "json_serializer" in src, (
            "SingleStore must import json_serializer from agno.db.utils "
            "so datetime/Decimal values in JSON columns don't crash json.dumps"
        )

    def test_passed_to_create_engine(self):
        """The import alone isn't enough — it must be handed to create_engine."""
        src = _module_source()
        assert "json_serializer=json_serializer" in src, (
            "json_serializer must be passed to create_engine(...) — "
            "otherwise SQLAlchemy uses the default json.dumps which chokes on "
            "datetime/Decimal/enums common in run_data / session_data blobs."
        )


class TestParityWithSiblingSqlAdapters:
    """Regression fence: if a future contributor drops the wiring from one
    of the SQL adapters, this catches it immediately."""

    @pytest.mark.parametrize(
        "module_path,class_name",
        [
            ("agno.db.mysql.mysql", "MySQLDb"),
            ("agno.db.postgres.postgres", "PostgresDb"),
            ("agno.db.singlestore.singlestore", "SingleStoreDb"),
        ],
    )
    def test_sql_adapter_uses_custom_json_serializer(self, module_path: str, class_name: str):
        try:
            module = __import__(module_path, fromlist=[class_name])
        except ImportError as e:
            pytest.skip(f"driver missing for {class_name}: {e}")
        src = inspect.getsource(module)
        assert "json_serializer=json_serializer" in src, (
            f"{class_name} must pass json_serializer to create_engine — "
            "otherwise non-JSON-native types (datetime, Decimal, enums) in "
            "JSON columns crash on insert."
        )
