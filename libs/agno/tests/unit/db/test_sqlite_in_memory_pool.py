from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from agno.db.sqlite import SqliteDb


@pytest.mark.parametrize("db_url", ["sqlite://", "sqlite:///:memory:"])
def test_in_memory_database_is_shared_with_worker_threads(db_url: str) -> None:
    db = SqliteDb(db_url=db_url, session_table="sessions")

    with db.db_engine.begin() as connection:
        connection.execute(text("CREATE TABLE items (value INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO items (value) VALUES (42)"))

    def read_value() -> int:
        with db.db_engine.connect() as connection:
            return connection.execute(text("SELECT value FROM items")).scalar_one()

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(read_value).result() == 42

    assert isinstance(db.db_engine.pool, StaticPool)
