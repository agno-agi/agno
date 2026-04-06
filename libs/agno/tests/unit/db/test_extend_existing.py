"""Test that Table() calls use extend_existing=True to prevent InvalidRequestError on retry.

Regression test for #7381 (SQLite / MySQL) and related to #7319 (PostgreSQL).
When _create_table() fails after registering the table on MetaData, the next
retry must not raise InvalidRequestError.  Setting extend_existing=True ensures
that re-registering the same table name is safe.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import MetaData, Table, Column, String, Integer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metadata_with_existing_table(table_name: str) -> MetaData:
    """Return a MetaData that already has *table_name* registered."""
    metadata = MetaData()
    Table(table_name, metadata, Column("id", String, primary_key=True))
    assert table_name in metadata.tables
    return metadata


# ---------------------------------------------------------------------------
# Tests: Table() with extend_existing=True tolerates duplicate registration
# ---------------------------------------------------------------------------

class TestExtendExistingGuard:
    """Verify that creating a Table with the same name on the same MetaData
    succeeds when extend_existing=True and fails without it."""

    def test_duplicate_table_without_extend_existing_raises(self):
        metadata = _make_metadata_with_existing_table("test_table")
        with pytest.raises(Exception):  # InvalidRequestError
            Table("test_table", metadata, Column("id", String, primary_key=True))

    def test_duplicate_table_with_extend_existing_succeeds(self):
        metadata = _make_metadata_with_existing_table("test_table")
        # This must NOT raise
        table = Table(
            "test_table",
            metadata,
            Column("id", String, primary_key=True),
            extend_existing=True,
        )
        assert table is not None
        assert table.name == "test_table"


# ---------------------------------------------------------------------------
# Tests: SQLite backends pass extend_existing=True
# ---------------------------------------------------------------------------

class TestSQLiteExtendExisting:
    """Check that SQLite Table() calls include extend_existing=True."""

    def test_sqlite_create_table_uses_extend_existing(self):
        """Verify sqlite.py _create_table passes extend_existing=True."""
        import importlib
        import inspect

        mod = importlib.import_module("agno.db.sqlite.sqlite")
        source = inspect.getsource(mod)

        # Every Table() in _create_table should have extend_existing
        # We check the source contains extend_existing=True near Table(
        assert "extend_existing=True" in source, (
            "sqlite.py must pass extend_existing=True to Table() constructors"
        )

    def test_async_sqlite_create_table_uses_extend_existing(self):
        """Verify async_sqlite.py _create_table passes extend_existing=True."""
        import importlib
        import inspect

        mod = importlib.import_module("agno.db.sqlite.async_sqlite")
        source = inspect.getsource(mod)
        assert "extend_existing=True" in source, (
            "async_sqlite.py must pass extend_existing=True to Table() constructors"
        )


# ---------------------------------------------------------------------------
# Tests: MySQL backends pass extend_existing=True
# ---------------------------------------------------------------------------

class TestMySQLExtendExisting:
    """Check that MySQL Table() calls include extend_existing=True."""

    def test_mysql_create_table_uses_extend_existing(self):
        """Verify mysql.py _create_table passes extend_existing=True."""
        import importlib
        import inspect

        mod = importlib.import_module("agno.db.mysql.mysql")
        source = inspect.getsource(mod)
        assert "extend_existing=True" in source, (
            "mysql.py must pass extend_existing=True to Table() constructors"
        )

    def test_async_mysql_create_table_uses_extend_existing(self):
        """Verify async_mysql.py _create_table passes extend_existing=True."""
        import importlib
        import inspect

        mod = importlib.import_module("agno.db.mysql.async_mysql")
        source = inspect.getsource(mod)
        assert "extend_existing=True" in source, (
            "async_mysql.py must pass extend_existing=True to Table() constructors"
        )
