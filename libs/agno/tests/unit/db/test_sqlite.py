from unittest.mock import Mock, patch

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session

from agno.db.sqlite.sqlite import SqliteDb


@pytest.fixture
def mock_session():
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.begin = Mock()
    session.begin().__enter__ = Mock(return_value=session)
    session.begin().__exit__ = Mock(return_value=None)
    return session


def test_failed_table_creation_can_be_retried(tmp_path, mock_session):
    """A failed CREATE TABLE must not leave the table registered on MetaData."""
    db = SqliteDb(db_engine=create_engine(f"sqlite:///{tmp_path}/retry.db"), session_table="test_sessions")
    db.Session = Mock(return_value=mock_session)
    attempts = {"retry_table": 0}

    def create_once(table, *args, **kwargs):
        if table.name == "retry_table":
            attempts["retry_table"] += 1
            if attempts["retry_table"] == 1:
                raise OSError("temporary DDL outage")

    with (
        patch.object(SqliteDb, "table_exists", return_value=False),
        patch("agno.db.sqlite.sqlite.is_table_available", return_value=False),
        patch.object(Table, "create", create_once),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            db._get_or_create_table("retry_table", "knowledge", True)

        table = db._get_or_create_table("retry_table", "knowledge", True)

    assert table.name == "retry_table"
    assert attempts["retry_table"] == 2
