from typing import Optional, Union
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url

from agno.tools.sql import SQLTools


@pytest.mark.parametrize(
    ("user", "password"),
    [
        ("agent", "plain-password"),
        ("agent", "p@ssword"),
        ("agent", "p%2Fword"),
        ("agent:name", "p:/?#@%word"),
    ],
)
@pytest.mark.parametrize("schema", [None, "agent_memory"])
def test_sql_tools_preserves_connection_parameters(user: str, password: str, schema: Optional[str]) -> None:
    """Reserved characters must reach SQLAlchemy unchanged without a database connection."""
    urls: list[URL] = []

    def build_engine(url: Union[str, URL]) -> Engine:
        urls.append(make_url(url))
        return create_engine("sqlite:///:memory:")

    with patch("agno.tools.sql.create_engine", side_effect=build_engine):
        tools = SQLTools(
            user=user,
            password=password,
            host="localhost",
            port=3306,
            schema=schema,
            dialect="mysql+pymysql",
        )

    try:
        assert len(urls) == 1
        url = urls[0]
        assert url.drivername == "mysql+pymysql"
        assert url.username == user
        assert url.password == password
        assert url.host == "localhost"
        assert url.port == 3306
        assert url.database == schema
        assert tools.schema == schema
    finally:
        tools.db_engine.dispose()
