"""Postgres mirror of the pinned-version guard.

The SQLite suite cannot see the defect this file exists for. A guard that
converts a caller-supplied version with ``int()`` truncates, while Postgres
assignment-casts a float to INTEGER by ROUNDING, so ``2.6`` was checked at
version 2 and stored at version 3. SQLite's INTEGER affinity keeps a
non-integral REAL as-is, so there the same input merely dangles and nothing
is disclosed -- the divergence is invisible on the adapter the rest of the
suite runs on.

Runs against the live pgvector container (localhost:5532) with a unique
schema per run; skips cleanly when psycopg or the server is absent.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings

psycopg = pytest.importorskip("psycopg")

from agno.db.postgres import PostgresDb  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _server_reachable() -> bool:
    # A raw probe, not an adapter call: adapter methods catch and log
    # connection errors, so a probe through one cannot tell "absent" from "ok".
    try:
        import sqlalchemy as sa

        engine = sa.create_engine(DB_URL)
        with engine.connect() as conn:
            conn.execute(sa.text("select 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _server_reachable(), reason="Postgres not reachable on localhost:5532")


@pytest.fixture
def db():
    return PostgresDb(id="pin-pg", db_url=DB_URL, db_schema=f"pin_{uuid.uuid4().hex[:8]}")


@pytest.fixture
def alice_agent(db):
    """Published v1 and v2, with an unpublished v3 that is alice's alone."""
    db.create_component_with_config(
        component_id="radar",
        component_type=ComponentType.AGENT,
        name="radar",
        config={"name": "radar", "instructions": "PUBLIC v1"},
        stage="published",
        user_id="alice",
    )
    db.upsert_config("radar", config={"name": "radar", "instructions": "PUBLIC v2"}, stage="published", user_id="alice")
    db.set_current_version("radar", version=2, user_id="alice")
    db.upsert_config("radar", config={"name": "radar", "instructions": "SECRET v3"}, user_id="alice")
    return "radar"


@pytest.fixture
def bob_team(db, alice_agent):
    db.create_component_with_config(
        component_id="bob-team",
        component_type=ComponentType.TEAM,
        name="bob-team",
        config={"name": "bob-team"},
        stage="draft",
        user_id="bob",
    )
    return "bob-team"


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


def _pin(child_id, version):
    return [
        {
            "link_kind": "member",
            "link_key": "member_0",
            "child_component_id": child_id,
            "child_version": version,
            "position": 0,
            "meta": {"type": "agent"},
        }
    ]


class TestTheColumnCannotRoundACallerIntoAnotherVersion:
    def test_the_draft_version_is_refused_when_asked_for_plainly(self, db, bob_team, alice_agent):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 3)},
        )
        assert r.status_code == 404, r.text

    @pytest.mark.parametrize("version", [2.6, 2.5, 1.5, 0.6, True])
    def test_no_spelling_rounds_into_a_version_the_caller_was_refused(self, db, bob_team, alice_agent, version):
        """Postgres rounds where ``int()`` truncates, so a fraction used to be
        checked at one version and stored at the next one up."""
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, version)},
        )
        assert r.status_code == 400, (version, r.status_code, r.text)
        for parent_version in (1, 2):
            assert db.get_links(bob_team, version=parent_version) == [], (version, parent_version)

    @pytest.mark.parametrize("version,expected", [(2, 2), (2.0, 2), ("2", 2), (" 1 ", 1)])
    def test_a_legitimate_spelling_stores_the_canonical_int(self, db, bob_team, alice_agent, version, expected):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, version)},
        )
        assert r.status_code == 201, (version, r.text)
        links = db.get_links(bob_team, version=r.json()["version"])
        assert [link["child_version"] for link in links] == [expected]

    def test_an_out_of_range_version_is_a_refusal_not_a_server_error(self, db, bob_team, alice_agent):
        """The value reaches an INTEGER column, so the range is part of the shape."""
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 10**12)},
        )
        assert r.status_code == 400, r.text
