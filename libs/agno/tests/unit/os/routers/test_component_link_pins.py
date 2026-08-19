"""A link names a version, and visibility is not readable depth.

Publishing shares one version of a component. A caller composing that
component supplies link rows, and each row names the child version to pin.
Nothing on the write path checked that version's stage, so a scoped caller
could pin another owner's unpublished version and then read it back
through the detail routes -- the exact disclosure
``GET /components/{id}/configs/{version}`` refuses to the same caller.

The refusal here is that route's, verbatim, so neither becomes an oracle
for the other.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="pin-db", db_file=str(tmp_path / "pin.db"))


def _client(db, user_id=None):
    app = FastAPI()

    @app.middleware("http")
    async def _scope(request, call_next):
        request.state.user_isolation_enabled = user_id is not None
        request.state.user_id = user_id
        request.state.scopes = []
        return await call_next(request)

    app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


@pytest.fixture
def alice_agent(db):
    """Published v1, plus an unpublished v2 that is alice's alone."""
    db.create_component_with_config(
        component_id="radar",
        component_type=ComponentType.AGENT,
        name="radar",
        config={"name": "radar", "instructions": "PUBLIC v1"},
        stage="published",
        user_id="alice",
    )
    db.upsert_config("radar", config={"name": "radar", "instructions": "SECRET v2"}, user_id="alice")
    return "radar"


@pytest.fixture
def bob_team(db, alice_agent):
    db.create_component_with_config(
        component_id="bob-team",
        component_type=ComponentType.TEAM,
        name="bob-team",
        config={"name": "bob-team", "members": [{"type": "agent", "agent_id": alice_agent}]},
        stage="draft",
        user_id="bob",
    )
    return "bob-team"


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


class TestPinningAnotherOwnersUnpublishedVersion:
    def test_create_config_refuses_the_pin(self, db, bob_team, alice_agent):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 404, (r.status_code, r.text)
        assert "SECRET" not in r.text

    def test_update_config_refuses_the_pin(self, db, bob_team, alice_agent):
        r = _client(db, "bob").patch(
            f"/components/{bob_team}/configs/1",
            json={"config": {"name": "bob-team"}, "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 404, (r.status_code, r.text)

    def test_the_refusal_matches_the_direct_read(self, db, bob_team, alice_agent):
        """Neither route may become an oracle for the other."""
        client = _client(db, "bob")
        pinned = client.post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        direct = client.get(f"/components/{alice_agent}/configs/2")
        assert pinned.status_code == direct.status_code == 404
        assert pinned.json()["detail"] == direct.json()["detail"]

    def test_no_link_row_survives_the_refusal(self, db, bob_team, alice_agent):
        _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert db.get_links(bob_team, version=2) == []


class TestTheLegitimateCompositionsStillWork:
    def test_pinning_the_published_version_is_allowed(self, db, bob_team, alice_agent):
        r = _client(db, "bob").post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 1)},
        )
        assert r.status_code == 201, (r.status_code, r.text)

    def test_the_owner_may_pin_their_own_draft(self, db, alice_agent):
        db.create_component_with_config(
            component_id="alice-team",
            component_type=ComponentType.TEAM,
            name="alice-team",
            config={"name": "alice-team"},
            stage="draft",
            user_id="alice",
        )
        r = _client(db, "alice").post(
            "/components/alice-team/configs",
            json={"config": {"name": "alice-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 201, (r.status_code, r.text)

    def test_an_unscoped_caller_is_not_gated(self, db, bob_team, alice_agent):
        r = _client(db).post(
            f"/components/{bob_team}/configs",
            json={"config": {"name": "bob-team"}, "stage": "draft", "links": _pin(alice_agent, 2)},
        )
        assert r.status_code == 201, (r.status_code, r.text)
