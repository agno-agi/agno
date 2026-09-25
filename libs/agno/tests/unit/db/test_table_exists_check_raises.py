import tempfile

import pytest
from sqlalchemy.exc import OperationalError

from agno.db.base import SessionType
from agno.db.mysql import utils as mysql_utils
from agno.db.postgres import utils as postgres_utils
from agno.db.singlestore import utils as singlestore_utils
from agno.db.sqlite import SqliteDb
from agno.db.sqlite import utils as sqlite_utils

_DISCONNECT = OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))


class _BrokenSession:
    def execute(self, *args, **kwargs):
        raise _DISCONNECT


class _BrokenAsyncSession:
    async def execute(self, *args, **kwargs):
        raise _DISCONNECT


@pytest.mark.parametrize(
    "check, kwargs",
    [
        (postgres_utils.is_table_available, {"db_schema": "ai"}),
        (mysql_utils.is_table_available, {"db_schema": "ai"}),
        (singlestore_utils.is_table_available, {"db_schema": "ai"}),
        (sqlite_utils.is_table_available, {}),
    ],
    ids=["postgres", "mysql", "singlestore", "sqlite"],
)
def test_a_failed_check_raises_instead_of_reporting_a_missing_table(check, kwargs):
    with pytest.raises(OperationalError):
        check(session=_BrokenSession(), table_name="agno_sessions", **kwargs)


@pytest.mark.parametrize(
    "check, kwargs",
    [
        (postgres_utils.ais_table_available, {"db_schema": "ai"}),
        (mysql_utils.ais_table_available, {"db_schema": "ai"}),
        (sqlite_utils.ais_table_available, {}),
    ],
    ids=["postgres", "mysql", "sqlite"],
)
async def test_a_failed_async_check_raises_instead_of_reporting_a_missing_table(check, kwargs):
    with pytest.raises(OperationalError):
        await check(session=_BrokenAsyncSession(), table_name="agno_sessions", **kwargs)


def _unopenable_db() -> SqliteDb:
    """A SqliteDb whose database file is a directory: every query fails with OperationalError."""
    return SqliteDb(db_file=tempfile.mkdtemp())


def test_table_exists_raises_when_the_database_cannot_be_reached():
    with pytest.raises(OperationalError):
        _unopenable_db().table_exists("agno_sessions")


def test_get_session_raises_instead_of_returning_no_session():
    with pytest.raises(OperationalError):
        _unopenable_db().get_session(session_id="s1", session_type=SessionType.AGENT)
