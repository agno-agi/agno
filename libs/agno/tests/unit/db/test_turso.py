from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import Engine

from agno.db.turso.turso import TursoDb, _extract_host, _normalize_remote_url


@pytest.fixture
def mock_engine():
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
    return engine


def test_id_is_deterministic(mock_engine):
    first_db = TursoDb(db_engine=mock_engine)
    second_db = TursoDb(db_engine=mock_engine)
    assert first_db.id == second_db.id


def test_init_with_engine(mock_engine):
    db = TursoDb(db_engine=mock_engine, session_table="sessions")
    assert db.db_engine is mock_engine
    assert db.session_table_name == "sessions"


@patch("agno.db.turso.turso.create_engine")
def test_init_remote_uses_connect_args(mock_create_engine):
    mock_create_engine.return_value = Mock(spec=Engine)

    TursoDb(url="libsql://my-db.turso.io", auth_token="test-token")

    mock_create_engine.assert_called_once()
    call_args, call_kwargs = mock_create_engine.call_args
    assert call_args[0] == "sqlite+libsql://my-db.turso.io/?secure=true"
    assert call_kwargs["connect_args"] == {"auth_token": "test-token"}


@patch("agno.db.turso.turso.create_engine")
def test_init_remote_strips_known_schemes(mock_create_engine):
    mock_create_engine.return_value = Mock(spec=Engine)

    TursoDb(url="https://my-db.turso.io", auth_token="t")
    assert mock_create_engine.call_args[0][0] == "sqlite+libsql://my-db.turso.io/?secure=true"

    mock_create_engine.reset_mock()
    TursoDb(url="my-db.turso.io", auth_token="t")
    assert mock_create_engine.call_args[0][0] == "sqlite+libsql://my-db.turso.io/?secure=true"


@patch("agno.db.turso.turso.create_engine")
def test_init_embedded_replica_uses_sync_url(mock_create_engine, tmp_path):
    mock_create_engine.return_value = Mock(spec=Engine)
    db_file = str(tmp_path / "replica.db")

    TursoDb(
        db_file=db_file,
        sync_url="libsql://remote.turso.io",
        auth_token="rep-token",
    )

    call_args, call_kwargs = mock_create_engine.call_args
    assert call_args[0] == f"sqlite+libsql:///{db_file}"
    assert call_kwargs["connect_args"] == {
        "sync_url": "libsql://remote.turso.io",
        "auth_token": "rep-token",
    }


def test_embedded_replica_requires_db_file():
    with pytest.raises(ValueError, match="db_file"):
        TursoDb(sync_url="libsql://remote.turso.io", auth_token="t")


def test_init_local_file_only_uses_libsql_url(tmp_path):
    db_file = str(tmp_path / "local.db")
    db = TursoDb(db_file=db_file)
    assert str(db.db_engine.url) == f"sqlite+libsql:///{db_file}"


def test_init_in_memory_default():
    db = TursoDb()
    assert str(db.db_engine.url) == "sqlite+libsql://"


def test_to_dict_contains_turso_fields(mock_engine):
    db = TursoDb(db_engine=mock_engine, id="fixed-id")
    d = db.to_dict()
    assert d["type"] == "turso"
    assert d["id"] == "fixed-id"
    assert "turso_url" in d
    assert "turso_sync_url" in d


def test_from_dict_roundtrip(tmp_path):
    db_file = str(tmp_path / "rt.db")
    original = TursoDb(db_file=db_file, id="rt-id", session_table="rt_sessions")
    restored = TursoDb.from_dict(original.to_dict())
    assert restored.id == "rt-id"
    assert restored.session_table_name == "rt_sessions"


def test_extract_host_handles_schemes():
    assert _extract_host("libsql://my-db.turso.io") == "my-db.turso.io"
    assert _extract_host("https://my-db.turso.io") == "my-db.turso.io"
    assert _extract_host("my-db.turso.io") == "my-db.turso.io"


def test_extract_host_rejects_empty():
    with pytest.raises(ValueError):
        _extract_host("")


def test_normalize_remote_url():
    assert _normalize_remote_url("https://my-db.turso.io") == "libsql://my-db.turso.io"
    assert _normalize_remote_url("libsql://my-db.turso.io") == "libsql://my-db.turso.io"


def test_async_turso_db_import_raises():
    """Async is intentionally not supported yet; surface a clear error."""
    import agno.db.turso as turso_pkg

    with pytest.raises(ImportError, match="not yet supported"):
        _ = turso_pkg.AsyncTursoDb
