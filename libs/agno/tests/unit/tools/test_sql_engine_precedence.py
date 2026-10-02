"""Explicit SQLAlchemy engines take precedence over connection settings."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from agno.tools.sql import SQLTools


@pytest.mark.parametrize("db_url", [None, "postgresql://unused:unused@localhost:5432/unused"])
def test_explicit_engine_takes_precedence_over_connection_settings(db_url):
    engine = create_engine("sqlite://")
    try:
        with patch("agno.tools.sql.create_engine", side_effect=AssertionError("must reuse supplied engine")):
            tools = SQLTools(
                db_engine=engine,
                db_url=db_url,
                user="unused",
                password="unused",
                host="localhost",
                port=5432,
                dialect="postgresql",
            )
        assert tools.db_engine is engine
        assert tools.run_sql("SELECT 42 AS answer") == [{"answer": 42}]
    finally:
        engine.dispose()
