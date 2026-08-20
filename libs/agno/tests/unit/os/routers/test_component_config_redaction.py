"""A shared component does not share the database behind it.

``_resolve_db_in_config`` stores the resolved database's full ``to_dict()``
in the component config so the component rebuilds without the registry. That
dict carries whatever the adapter exposes -- a credentialed ``db_url`` on
Postgres, a filesystem path on SQLite, a plaintext ``password`` on
ClickHouse. Publishing a component now makes its config readable by every
actor, so the read path has to hand out the component without handing out
the connection.

The keep-list is positive on purpose: an adapter that grows a new
connection field must not silently start leaking it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings

CONNECTION_KEYS = ("db_url", "db_file", "db_schema", "password", "username", "host", "port")


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="redact-db", db_file=str(tmp_path / "redact.db"))


@pytest.fixture
def published(db):
    db.create_component_with_config(
        component_id="alice-agent",
        component_type=ComponentType.AGENT,
        name="alice-agent",
        config={
            "name": "alice-agent",
            "db": {
                "id": "prod",
                "type": "postgres",
                "db_url": "postgresql+psycopg://user:hunter2@prod-host/agno",
                "db_schema": "ai",
                "password": "hunter2",
                "session_table": "alice_sessions",
            },
        },
        stage="published",
        user_id="alice",
    )
    return "alice-agent"


def _client(db, user_id):
    app = FastAPI()

    @app.middleware("http")
    async def _scope(request, call_next):
        request.state.user_isolation_enabled = True
        request.state.user_id = user_id
        request.state.scopes = []
        return await call_next(request)

    app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


def _unscoped_write_client(db, user_id):
    """Authenticated, but user_isolation off: writes are unscoped."""
    app = FastAPI()

    @app.middleware("http")
    async def _scope(request, call_next):
        request.state.user_isolation_enabled = False
        request.state.user_id = user_id
        request.state.scopes = []
        return await call_next(request)

    app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


ROUTES = [
    "/components/alice-agent/configs",
    "/components/alice-agent/configs/current",
    "/components/alice-agent/configs/1",
]


class TestANonOwnerReadsTheComponentButNotTheConnection:
    @pytest.mark.parametrize("route", ROUTES)
    def test_the_connection_fields_are_gone(self, db, published, route):
        r = _client(db, "bob").get(route)
        assert r.status_code == 200, (r.status_code, r.text)
        for key in CONNECTION_KEYS:
            assert key not in r.text, (key, r.text)

    @pytest.mark.parametrize("route", ROUTES)
    def test_the_component_is_still_usable(self, db, published, route):
        """Redaction removes the connection, not the component."""
        r = _client(db, "bob").get(route)
        body = r.json()
        config = (body[0] if isinstance(body, list) else body)["config"]
        assert config["name"] == "alice-agent"
        assert config["db"]["id"] == "prod"
        assert config["db"]["type"] == "postgres"
        assert config["db"]["session_table"] == "alice_sessions"


class TestTheOwnerAndTheAdminReadItWhole:
    @pytest.mark.parametrize("route", ROUTES)
    def test_the_owner_still_sees_the_connection(self, db, published, route):
        r = _client(db, "alice").get(route)
        assert r.status_code == 200, (r.status_code, r.text)
        assert "hunter2" in r.text

    @pytest.mark.parametrize("route", ROUTES)
    def test_an_unscoped_caller_still_sees_the_connection(self, db, published, route):
        app = FastAPI()
        app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
        r = TestClient(app).get(route)
        assert r.status_code == 200, (r.status_code, r.text)
        assert "hunter2" in r.text


class TestNestedBlocksAreRedactedToo:
    def test_a_member_config_cannot_smuggle_the_connection_out(self, db):
        db.create_component_with_config(
            component_id="alice-team",
            component_type=ComponentType.TEAM,
            name="alice-team",
            config={
                "name": "alice-team",
                "members": [{"name": "m1", "db": {"id": "prod", "type": "postgres", "db_url": "postgresql://s3cret"}}],
            },
            stage="published",
            user_id="alice",
        )
        r = _client(db, "bob").get("/components/alice-team/configs/current")
        assert r.status_code == 200, (r.status_code, r.text)
        assert "s3cret" not in r.text
        assert r.json()["config"]["members"][0]["db"]["id"] == "prod"


class TestASharedComponentIsReadWhole:
    """Redaction is for configs the caller cannot write back.

    An unowned row -- what `agent.save(db=...)` produces, and anything created
    before ownership stamping -- is readable AND writable by every
    authenticated caller. The only write the API offers is a whole config, so
    redacting the read and accepting it back on the next save would destroy
    the stored connection; for a nested block that loss is permanent, because
    the resolver repairs only the top-level one.
    """

    @pytest.fixture
    def shared(self, db):
        db.create_component_with_config(
            component_id="shared-agent",
            component_type=ComponentType.AGENT,
            name="shared-agent",
            config={
                "name": "shared-agent",
                "db": {"id": "prod", "type": "postgres", "db_url": "postgresql://user:hunter2@h/db"},
            },
            stage="published",
        )
        return "shared-agent"

    @pytest.mark.parametrize("route", ["/components/shared-agent/configs", "/components/shared-agent/configs/current"])
    def test_an_authenticated_caller_reads_it_whole(self, db, shared, route):
        r = _client(db, "bob").get(route)
        assert r.status_code == 200, (r.status_code, r.text)
        assert "hunter2" in r.text

    def test_a_read_modify_write_keeps_the_connection(self, db, shared):
        # user_isolation OFF is the default and the shape that matters:
        # get_scoped_user_id returns None so the write guard never fires, while
        # draft_preview_identity still reports the JWT subject. The two rules
        # disagreeing is exactly what made the round trip lossy.
        client = _unscoped_write_client(db, "bob")
        config = client.get("/components/shared-agent/configs/current").json()["config"]
        config["name"] = "renamed"
        assert client.post("/components/shared-agent/configs", json={"config": config}).status_code == 201
        stored = db.get_config("shared-agent", version=2)["config"]
        assert stored["db"]["db_url"] == "postgresql://user:hunter2@h/db"

    def test_another_owners_component_is_still_redacted(self, db, published):
        """The rule narrowed to unowned rows, not to nothing."""
        r = _client(db, "bob").get(f"/components/{published}/configs/current")
        assert r.status_code == 200
        assert "hunter2" not in r.text
