"""Unit tests for SQLCipher-backed SQLite engines."""

import sqlite3
from unittest.mock import patch

import pytest

sqlcipher3 = pytest.importorskip("sqlcipher3")
pytest.importorskip("aiosqlcipher")

from sqlalchemy import text

from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.db.sqlite.sqlite import SqliteDb


@pytest.fixture
def passphrase():
    return "agno-test-passphrase"


def test_sqlite_encrypted_roundtrip(tmp_path, passphrase):
    db_path = tmp_path / "encrypted.db"
    db = SqliteDb(db_file=str(db_path), passphrase=passphrase)

    assert db.encrypted is True
    assert db.passphrase_env is None

    with db.Session() as sess:
        sess.execute(text("CREATE TABLE IF NOT EXISTS _agno_enc_test (id INTEGER)"))
        sess.commit()
        assert sess.execute(text("SELECT 1")).scalar() == 1

    assert db_path.stat().st_size > 0
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(db_path).execute("SELECT name FROM sqlite_master").fetchall()

    serialized = db.to_dict()
    assert serialized["encrypted"] is True
    assert "passphrase" not in serialized
    assert "passphrase_env" not in serialized

    db.close()


def test_sqlite_encrypted_from_dict_requires_passphrase_env(tmp_path, passphrase, monkeypatch):
    db_path = tmp_path / "encrypted_env.db"
    monkeypatch.setenv("AGNO_SQLITE_KEY", passphrase)

    original = SqliteDb(db_file=str(db_path), passphrase_env="AGNO_SQLITE_KEY")
    data = original.to_dict()
    assert data["passphrase_env"] == "AGNO_SQLITE_KEY"

    restored = SqliteDb.from_dict(data)
    assert restored.encrypted is True

    with restored.Session() as sess:
        assert sess.execute(text("SELECT 1")).scalar() == 1

    original.close()
    restored.close()


def test_sqlite_encrypted_from_dict_missing_env_raises():
    with pytest.raises(ValueError, match="passphrase_env"):
        SqliteDb.from_dict({"db_file": "/tmp/x.db", "encrypted": True})


@pytest.mark.asyncio
async def test_async_sqlite_encrypted_roundtrip(tmp_path, passphrase):
    db_path = tmp_path / "encrypted_async.db"
    db = AsyncSqliteDb(db_file=str(db_path), passphrase=passphrase)

    assert db.encrypted is True

    async with db.async_session_factory() as sess:
        await sess.execute(text("CREATE TABLE IF NOT EXISTS _agno_enc_test (id INTEGER)"))
        await sess.commit()
        result = await sess.execute(text("SELECT 1"))
        assert result.scalar() == 1

    assert db_path.stat().st_size > 0
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(db_path).execute("SELECT name FROM sqlite_master").fetchall()

    await db.close()


def test_sqlite_passphrase_and_db_url_mutually_exclusive(passphrase):
    with pytest.raises(ValueError, match="db_url"):
        SqliteDb(db_url="sqlite:///:memory:", passphrase=passphrase)


def test_sqlite_missing_sqlcipher_extra_message(passphrase):
    from agno.db.sqlite.engine import SQLCIPHER_INSTALL_HINT

    with patch("agno.db.sqlite.engine._import_sqlcipher3", side_effect=ImportError(SQLCIPHER_INSTALL_HINT)):
        with pytest.raises(ImportError, match="sqlite-encrypted"):
            SqliteDb(db_file="tmp/test.db", passphrase=passphrase)
