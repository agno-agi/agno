import pytest
from sqlalchemy import create_engine, text

from agno.db.mysql import MySQLDb

MYSQL_URL = "mysql+pymysql://ai:ai@localhost:3306/ai"


@pytest.fixture(scope="session")
def mysql_engine():
    """Engine for a local MySQL, skipping the suite when none is reachable."""
    try:
        engine = create_engine(MYSQL_URL)
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"MySQL not available at localhost:3306: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture
def mysql_db(mysql_engine, request):
    """A MySQLDb on a table unique to each test, dropped afterwards."""
    table = f"test_sessions_{abs(hash(request.node.nodeid)) % 100000}"
    db = MySQLDb(db_engine=mysql_engine, session_table=table)
    yield db
    with mysql_engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
