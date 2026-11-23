from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import Table

from agno.db.mysql.mysql import MySQLDb


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine."""
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    return engine


@pytest.fixture
def mock_session():
    """Create a mock session."""
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.begin = Mock()
    session.begin().__enter__ = Mock(return_value=session)
    session.begin().__exit__ = Mock(return_value=None)
    return session


@pytest.fixture
def mysql_db(mock_engine):
    """Create a MySQLDb instance with mock engine."""
    return MySQLDb(
        db_engine=mock_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        knowledge_table="test_knowledge",
    )


def test_failed_table_creation_can_be_retried(mysql_db, mock_session):
    """A failed CREATE TABLE must not leave the table registered on MetaData."""
    mysql_db.Session = Mock(return_value=mock_session)
    mysql_db.create_schema = False
    attempts = {"retry_table": 0}

    def create_once(table, *args, **kwargs):
        if table.name == "retry_table":
            attempts["retry_table"] += 1
            if attempts["retry_table"] == 1:
                raise OSError("temporary DDL outage")

    with (
        patch.object(MySQLDb, "table_exists", return_value=False),
        patch("agno.db.mysql.mysql.is_table_available", return_value=False),
        patch.object(Table, "create", create_once),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            mysql_db._get_or_create_table("retry_table", "knowledge", True)

        table = mysql_db._get_or_create_table("retry_table", "knowledge", True)

    assert table.name == "retry_table"
    assert attempts["retry_table"] == 2
