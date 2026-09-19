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


class TestRedactionFollowsTheWriteRule:
    """Redaction is decided by the write rule, not by a rule of its own.

    The only write the API offers is a whole config, so a caller that may save
    a row must be shown that row whole: hand it a redacted body and its next
    save stores the redaction, destroying the connection. A caller that may
    NOT save the row has no such claim on the connection, so it reads without.

    Both halves are pinned against BOTH clients on purpose. The predicate used
    to be read from an identity that ignores ``user_isolation`` while the write
    guard read one that honours it, and a suite that asserted the read under
    one client and the write under the other could not see them disagree.
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
    def test_a_scoped_caller_cannot_write_a_shared_row_so_it_reads_redacted(self, db, shared, route):
        client = _client(db, "bob")
        assert "hunter2" not in client.get(route).text
        # The other half of the rule, in the same test: this caller really is
        # refused the write, so nothing was taken away from it.
        config = client.get("/components/shared-agent/configs/current").json()["config"]
        assert client.post("/components/shared-agent/configs", json={"config": config}).status_code == 403

    def test_an_unscoped_caller_may_write_a_shared_row_so_it_reads_it_whole(self, db, shared):
        client = _unscoped_write_client(db, "bob")
        config = client.get("/components/shared-agent/configs/current").json()["config"]
        assert config["db"]["db_url"] == "postgresql://user:hunter2@h/db"
        config["name"] = "renamed"
        assert client.post("/components/shared-agent/configs", json={"config": config}).status_code == 201
        stored = db.get_config("shared-agent", version=2)["config"]
        assert stored["db"]["db_url"] == "postgresql://user:hunter2@h/db"

    def test_another_owners_component_is_still_redacted(self, db, published):
        r = _client(db, "bob").get(f"/components/{published}/configs/current")
        assert r.status_code == 200
        assert "hunter2" not in r.text


class TestAnUnscopedCallerRoundTripsAnotherOwnersConfig:
    """The regression this predicate was changed to fix.

    With ``user_isolation`` off -- the default -- every authenticated caller is
    unscoped: it may edit, and even delete, any owner's component. Redacting
    its read while accepting its write turned an ordinary authorised edit into
    silent data loss, and no test covered it because the suite asserted reads
    under the scoped client and writes under the unscoped one.
    """

    @pytest.fixture
    def alice_team(self, db):
        db.create_component_with_config(
            component_id="alice-team",
            component_type=ComponentType.TEAM,
            name="alice-team",
            config={
                "name": "alice-team",
                "db": {"id": "prod", "type": "postgres", "db_url": "postgresql://u:hunter2@h/agno"},
                "members": [
                    {"name": "m1", "db": {"id": "prod", "type": "postgres", "db_url": "postgresql://u:nested@h/agno"}}
                ],
            },
            stage="published",
            user_id="alice",
        )
        return "alice-team"

    def test_the_stored_connection_survives_the_round_trip(self, db, alice_team):
        client = _unscoped_write_client(db, "bob")
        config = client.get(f"/components/{alice_team}/configs/current").json()["config"]
        config["name"] = "renamed by bob"
        assert client.post(f"/components/{alice_team}/configs", json={"config": config}).status_code == 201

        stored = db.get_config(alice_team, version=2)["config"]
        assert stored["db"]["db_url"] == "postgresql://u:hunter2@h/agno"
        # The nested block is the half no resolver repairs, so it is the half
        # that proves the read was not redacted rather than merely repaired.
        assert stored["members"][0]["db"]["db_url"] == "postgresql://u:nested@h/agno"
