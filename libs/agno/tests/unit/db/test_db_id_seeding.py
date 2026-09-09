"""A db's generated id is its identity: everything that tells two databases
apart (registry dedup, stored-config resolution, the catalog fallback guard,
Studio's shared-machine disclosure) keys on it. The seed expressions used to
bind the conditional over the whole or-chain, so without an engine every
instance seeded from the literal default and physically different databases
shared one id. These tests pin the corrected seeding: distinct targets get
distinct ids, the same target keeps getting the same id.

The MySQL and SingleStore cases require their drivers, so locally they may
skip; CI installs the extras and runs them.
"""

import pytest

from agno.db.sqlite import SqliteDb


class TestSqliteIdSeeding:
    def test_different_files_get_different_ids(self, tmp_path):
        a = SqliteDb(db_file=str(tmp_path / "components.db"))
        b = SqliteDb(db_file=str(tmp_path / "learning.db"))
        assert a.id != b.id

    def test_same_target_gets_the_same_id(self, tmp_path):
        path = str(tmp_path / "shared.db")
        assert SqliteDb(db_file=path).id == SqliteDb(db_file=path).id
        # The no-argument default is one shared target, so one shared id.
        assert SqliteDb().id == SqliteDb().id

    def test_url_seeds_and_differs_from_the_default(self, tmp_path):
        by_url = SqliteDb(db_url="sqlite:///" + str(tmp_path / "learning.db"))
        assert by_url.id != SqliteDb().id
        assert by_url.id != SqliteDb(db_file=str(tmp_path / "components.db")).id

    def test_explicit_id_wins(self, tmp_path):
        assert SqliteDb(id="mine", db_file=str(tmp_path / "x.db")).id == "mine"


class TestAsyncSqliteIdSeeding:
    def test_different_files_get_different_ids(self, tmp_path):
        pytest.importorskip("aiosqlite")
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        a = AsyncSqliteDb(db_file=str(tmp_path / "components.db"))
        b = AsyncSqliteDb(db_file=str(tmp_path / "learning.db"))
        assert a.id != b.id
        assert AsyncSqliteDb(db_file=str(tmp_path / "components.db")).id == a.id


class TestMySQLAndSingleStoreIdSeeding:
    def test_async_mysql_url_seeds_the_id(self):
        pytest.importorskip("aiomysql")
        from agno.db.mysql.async_mysql import AsyncMySQLDb

        a = AsyncMySQLDb(db_url="mysql+aiomysql://u:p@h:3306/one", session_table="s")
        b = AsyncMySQLDb(db_url="mysql+aiomysql://u:p@h:3306/two", session_table="s")
        assert a.id != b.id
        assert AsyncMySQLDb(db_url="mysql+aiomysql://u:p@h:3306/one", session_table="s").id == a.id

    def test_singlestore_url_seeds_the_id(self):
        pytest.importorskip("pymysql")
        from agno.db.singlestore.singlestore import SingleStoreDb

        a = SingleStoreDb(db_url="mysql+pymysql://u:p@h:3306/one", session_table="s")
        b = SingleStoreDb(db_url="mysql+pymysql://u:p@h:3306/two", session_table="s")
        assert a.id != b.id
