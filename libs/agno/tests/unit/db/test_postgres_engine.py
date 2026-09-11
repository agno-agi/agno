"""Engine configuration is validated without connecting to PostgreSQL."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import event
from sqlalchemy.engine import URL, make_url

from agno.db.postgres import (
    AsyncPostgresDb,
    PostgresDb,
    create_async_postgres_engine,
    create_postgres_engine,
)


@pytest.fixture(params=[create_postgres_engine, create_async_postgres_engine])
def factory(request):
    return request.param


def sync_engine(engine):
    return getattr(engine, "sync_engine", engine)


def test_defaults_and_json_values(factory):
    engine = sync_engine(factory("postgresql://user:password@localhost/db"))
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 3600
    encoded = engine.dialect._json_serializer({"created": datetime(2026, 1, 2)})
    assert json.loads(encoded) == {"created": "2026-01-02T00:00:00"}
    assert engine.pool.checkedout() == 0
    engine.dispose()


def test_overrides_preserve_other_defaults(factory):
    options = {"pool_pre_ping": False, "pool_recycle": 120, "pool_size": 2, "max_overflow": 0}
    engine = sync_engine(factory("postgres://user:password@localhost/db", **options))
    assert engine.pool._pre_ping is False
    assert engine.pool._recycle == 120
    assert engine.pool.size() == 2
    assert engine.pool._max_overflow == 0
    assert json.loads(engine.dialect._json_serializer({"value": 1})) == {"value": 1}
    engine.dispose()


def test_custom_serializer(factory):
    def serializer(value):
        return "custom"

    engine = sync_engine(factory("postgresql://user:password@localhost/db", json_serializer=serializer))
    assert engine.dialect._json_serializer is serializer
    engine.dispose()


def test_url_object_preserves_credentials_and_tls(factory):
    url = URL.create(
        "postgresql",
        username="user@name",
        password="p@ss:/?#%",
        host="localhost",
        database="db",
        query={"sslmode": "verify-full", "sslrootcert": "/path with spaces/ca.pem"},
    )
    engine = sync_engine(factory(url))
    assert url.drivername == "postgresql"
    assert engine.url.password == url.password
    assert engine.url.username == url.username
    assert engine.url.query == url.query
    _, params = engine.dialect.create_connect_args(engine.url)
    assert params["password"] == "p@ss:/?#%"
    assert params["sslrootcert"] == "/path with spaces/ca.pem"
    engine.dispose()


def test_connect_args_reach_driver_without_network(factory):
    options = {"connect_timeout": 3, "prepare_threshold": None}
    engine = sync_engine(factory("postgresql://user:password@localhost/db", connect_args=options))
    captured = {}

    class StopBeforeNetwork(Exception):
        pass

    @event.listens_for(engine, "do_connect")
    def capture(dialect, record, args, params):
        captured.update(params)
        raise StopBeforeNetwork

    with pytest.raises(StopBeforeNetwork):
        engine.connect()
    assert captured["connect_timeout"] == 3
    assert captured["prepare_threshold"] is None
    assert options == {"connect_timeout": 3, "prepare_threshold": None}
    engine.dispose()


@pytest.mark.parametrize(
    "factory_name,sqlalchemy_name,driver",
    [
        ("create_postgres_engine", "create_engine", "postgresql+psycopg2"),
        ("create_async_postgres_engine", "create_async_engine", "postgresql+asyncpg"),
    ],
)
def test_explicit_driver_preserved(factory_name, sqlalchemy_name, driver):
    from agno.db.postgres import engine as module

    url = f"{driver}://user:p%40ss@localhost/db?sslrootcert=system"
    with patch.object(module, sqlalchemy_name) as create:
        getattr(module, factory_name)(url)
    assert create.call_args.args[0] == make_url(url)


def test_other_database_rejected_without_echoing_credentials(factory):
    with pytest.raises(ValueError, match="^Expected a PostgreSQL URL$"):
        factory("mysql://user:secret@localhost/db")


def test_factories_create_independent_pools(factory):
    first = sync_engine(factory("postgresql://user:password@localhost/db"))
    second = sync_engine(factory("postgresql://user:password@localhost/db"))
    assert first.pool is not second.pool
    first.dispose()
    second.dispose()


@pytest.mark.parametrize("db_class", [PostgresDb, AsyncPostgresDb])
def test_database_url_path_uses_same_defaults(db_class):
    db = db_class(db_url="postgresql+psycopg://user:password@localhost/db")
    engine = sync_engine(db.db_engine)
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.pool._pre_ping is True
    assert engine.pool._recycle == 3600
    engine.dispose()


def test_shared_engine_does_not_serialize_credentials():
    engine = create_postgres_engine("postgresql://user:secret@localhost/db")
    db = PostgresDb(id="shared-db", db_engine=engine)
    assert db.db_engine is engine
    assert db.to_dict()["db_url"] is None
    engine.dispose()
