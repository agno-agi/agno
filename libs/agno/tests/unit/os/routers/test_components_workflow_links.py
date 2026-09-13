"""Component write routes: derived links, rollback re-projection and the
detail a scoped caller gets on a 409.

Every one of these is a case where an invariant held on one route and not on
the sibling route that reaches the same state - a workflow written through
REST kept none of the link rows the SDK writes, a PATCH could store an empty
composition next to a live link row, a rollback moved the pointer without the
row following it, and a scoped caller was handed a dependents claim in place
of the real cause.
"""

from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings


@pytest.fixture
def db(tmp_path) -> SqliteDb:
    return SqliteDb(id="components-links-db", db_file=str(tmp_path / "components_links.db"))


def make_client(db: SqliteDb, user_id: Optional[str] = None) -> TestClient:
    """A client whose requests are scoped to ``user_id``, or unscoped (admin)."""
    app = FastAPI()
    if user_id is not None:

        @app.middleware("http")
        async def scope_requests(request, call_next):
            request.state.user_isolation_enabled = True
            request.state.user_id = user_id
            request.state.scopes = []
            return await call_next(request)

    app.include_router(get_components_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


def create_agent(client: TestClient, component_id: str, stage: str = "published") -> None:
    response = client.post(
        "/components",
        json={
            "name": component_id,
            "component_id": component_id,
            "component_type": "agent",
            "config": {"name": component_id, "id": component_id},
            "stage": stage,
        },
    )
    assert response.status_code == 201, response.text


def step(name: str, agent_id: str) -> Dict[str, Any]:
    return {"type": "Step", "name": name, "step_id": name, "agent_id": agent_id}


def links_for(db: SqliteDb, component_id: str, version: int) -> List[Dict[str, Any]]:
    return db.get_links(component_id=component_id, version=version)


class TestWorkflowStepLinksOnWriteRoutes:
    """A step's agent must become a dependent of the workflow, exactly as a
    team member does. Without the row the archive guard fails open."""

    def test_create_workflow_pins_its_step_agents(self, db):
        client = make_client(db)
        create_agent(client, "step-agent")

        response = client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {"name": "wf", "id": "wf", "steps": [step("s1", "step-agent")]},
                "stage": "published",
            },
        )
        assert response.status_code == 201, response.text

        rows = links_for(db, "wf", 1)
        assert [
            (row["link_kind"], row["link_key"], row["child_component_id"], row["child_version"]) for row in rows
        ] == [("step_agent", "s1", "step-agent", 1)]
        assert client.delete("/components/step-agent").status_code == 409

    def test_new_config_version_pins_its_step_agents(self, db):
        client = make_client(db)
        create_agent(client, "step-agent")
        create_agent(client, "later-agent")
        client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {"name": "wf", "id": "wf", "steps": [step("s1", "step-agent")]},
                "stage": "published",
            },
        )

        response = client.post(
            "/components/wf/configs",
            json={
                "config": {"name": "wf", "id": "wf", "steps": [step("s1", "later-agent")]},
                "stage": "published",
            },
        )
        assert response.status_code == 201, response.text

        assert [row["child_component_id"] for row in links_for(db, "wf", 2)] == ["later-agent"]
        assert client.delete("/components/later-agent").status_code == 409

    def test_patch_of_a_draft_pins_its_step_agents(self, db):
        client = make_client(db)
        create_agent(client, "step-agent")
        client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {"name": "wf", "id": "wf", "steps": []},
                "stage": "draft",
            },
        )

        response = client.patch(
            "/components/wf/configs/1",
            json={"config": {"name": "wf", "id": "wf", "steps": [step("s1", "step-agent")]}},
        )
        assert response.status_code == 200, response.text

        assert [row["child_component_id"] for row in links_for(db, "wf", 1)] == ["step-agent"]
        assert client.delete("/components/step-agent").status_code == 409

    def test_else_branch_steps_do_not_collide_with_the_if_branch(self, db):
        client = make_client(db)
        create_agent(client, "if-agent")
        create_agent(client, "else-agent")

        response = client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {
                    "name": "wf",
                    "id": "wf",
                    "steps": [
                        {
                            "type": "Condition",
                            "name": "cond",
                            "steps": [step("branch", "if-agent")],
                            "else_steps": [step("branch", "else-agent")],
                        }
                    ],
                },
                "stage": "published",
            },
        )
        assert response.status_code == 201, response.text

        rows = {row["link_key"]: row["child_component_id"] for row in links_for(db, "wf", 1)}
        assert rows == {"branch": "if-agent", "branch#else": "else-agent"}

    def test_a_draft_only_step_agent_is_not_pinned(self, db):
        """A link pins a published version; pinning a draft would refuse the
        parent's own publish."""
        client = make_client(db)
        create_agent(client, "draft-agent", stage="draft")

        response = client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {"name": "wf", "id": "wf", "steps": [step("s1", "draft-agent")]},
                "stage": "published",
            },
        )
        assert response.status_code == 201, response.text
        assert links_for(db, "wf", 1) == []

    def test_a_step_naming_no_stored_component_is_accepted(self, db):
        """A step may name a code-defined executor this process cannot see."""
        client = make_client(db)

        response = client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {"name": "wf", "id": "wf", "steps": [step("s1", "code-defined-agent")]},
                "stage": "published",
            },
        )
        assert response.status_code == 201, response.text
        assert links_for(db, "wf", 1) == []


class TestConfigPatchClearsLinks:
    """A version that stores an empty composition must not keep a live link
    row: the ex-child could never be archived again."""

    def _team_with_member(self, client: TestClient, team_id: str, member_id: str) -> None:
        create_agent(client, member_id)
        response = client.post(
            "/components",
            json={
                "name": team_id,
                "component_id": team_id,
                "component_type": "team",
                "config": {"name": team_id, "id": team_id, "members": [{"type": "agent", "agent_id": member_id}]},
                "stage": "draft",
            },
        )
        assert response.status_code == 201, response.text

    def test_patch_emptying_members_clears_the_rows(self, db):
        client = make_client(db)
        self._team_with_member(client, "team", "member")
        assert links_for(db, "team", 1)

        response = client.patch(
            "/components/team/configs/1",
            json={"config": {"name": "team", "id": "team", "members": []}},
        )
        assert response.status_code == 200, response.text

        assert links_for(db, "team", 1) == []
        assert client.delete("/components/member").status_code == 204

    def test_patch_to_a_config_without_members_clears_the_rows(self, db):
        """The config blob is replaced, not merged, so a body that drops the
        members key really does store a team with no members."""
        client = make_client(db)
        self._team_with_member(client, "team", "member")

        response = client.patch("/components/team/configs/1", json={"config": {"name": "renamed"}})
        assert response.status_code == 200, response.text

        assert db.get_config("team", version=1)["config"] == {"name": "renamed"}
        assert links_for(db, "team", 1) == []
        assert client.delete("/components/member").status_code == 204

    def test_patch_swapping_members_moves_the_pin(self, db):
        client = make_client(db)
        self._team_with_member(client, "team", "member-a")
        create_agent(client, "member-b")

        response = client.patch(
            "/components/team/configs/1",
            json={
                "config": {"name": "team", "id": "team", "members": [{"type": "agent", "agent_id": "member-b"}]},
            },
        )
        assert response.status_code == 200, response.text

        assert [row["child_component_id"] for row in links_for(db, "team", 1)] == ["member-b"]
        assert client.delete("/components/member-a").status_code == 204
        assert client.delete("/components/member-b").status_code == 409

    def test_patch_to_members_this_process_cannot_resolve_still_clears(self, db):
        """The old row must go even when the new composition derives nothing."""
        client = make_client(db)
        self._team_with_member(client, "team", "member")

        response = client.patch(
            "/components/team/configs/1",
            json={
                "config": {"name": "team", "id": "team", "members": [{"type": "agent", "agent_id": "code-defined"}]},
            },
        )
        assert response.status_code == 200, response.text

        assert links_for(db, "team", 1) == []
        assert client.delete("/components/member").status_code == 204

    def test_patch_emptying_workflow_steps_clears_the_rows(self, db):
        client = make_client(db)
        create_agent(client, "step-agent")
        client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {"name": "wf", "id": "wf", "steps": [step("s1", "step-agent")]},
                "stage": "draft",
            },
        )
        assert links_for(db, "wf", 1)

        response = client.patch(
            "/components/wf/configs/1",
            json={"config": {"name": "wf", "id": "wf", "steps": []}},
        )
        assert response.status_code == 200, response.text

        assert links_for(db, "wf", 1) == []
        assert client.delete("/components/step-agent").status_code == 204

    def test_a_stage_only_patch_keeps_the_pins(self, db):
        """No config in the body means nothing to derive from - the rows the
        version already carries must survive."""
        client = make_client(db)
        self._team_with_member(client, "team", "member")

        response = client.patch("/components/team/configs/1", json={"stage": "published"})
        assert response.status_code == 200, response.text

        assert [row["child_component_id"] for row in links_for(db, "team", 1)] == ["member"]
        assert client.delete("/components/member").status_code == 409

    def test_explicit_links_still_win(self, db):
        client = make_client(db)
        self._team_with_member(client, "team", "member")
        create_agent(client, "other")

        response = client.patch(
            "/components/team/configs/1",
            json={
                "config": {"name": "team", "id": "team", "members": []},
                "links": [
                    {
                        "link_kind": "member",
                        "link_key": "member_0",
                        "child_component_id": "other",
                        "child_version": 1,
                        "position": 0,
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        assert [row["child_component_id"] for row in links_for(db, "team", 1)] == ["other"]


class TestMalformedMemberReferences:
    """Client input must not produce a 5xx."""

    def _team(self, client: TestClient) -> None:
        create_agent(client, "member")
        response = client.post(
            "/components",
            json={
                "name": "team",
                "component_id": "team",
                "component_type": "team",
                "config": {"name": "team", "id": "team", "members": [{"type": "agent", "agent_id": "member"}]},
                "stage": "draft",
            },
        )
        assert response.status_code == 201, response.text

    def test_non_string_member_id_on_create_config(self, db):
        client = make_client(db)
        self._team(client)

        response = client.post(
            "/components/team/configs",
            json={"config": {"name": "team", "id": "team", "members": [{"type": "agent", "agent_id": ["member"]}]}},
        )
        assert response.status_code < 500, response.text

    def test_non_string_member_id_on_update_config(self, db):
        client = make_client(db)
        self._team(client)

        response = client.patch(
            "/components/team/configs/1",
            json={"config": {"name": "team", "id": "team", "members": [{"type": "agent", "agent_id": {"a": 1}}]}},
        )
        assert response.status_code < 500, response.text

    def test_non_string_step_agent_id_on_create_config(self, db):
        client = make_client(db)
        client.post(
            "/components",
            json={
                "name": "wf",
                "component_id": "wf",
                "component_type": "workflow",
                "config": {"name": "wf", "id": "wf", "steps": []},
                "stage": "draft",
            },
        )

        response = client.post(
            "/components/wf/configs",
            json={
                "config": {
                    "name": "wf",
                    "id": "wf",
                    "steps": [{"type": "Step", "name": "s1", "step_id": "s1", "agent_id": [1, 2]}],
                }
            },
        )
        assert response.status_code < 500, response.text


class TestRollbackReprojectsTheCatalogRow:
    """Moving the current pointer is a rollback: the row's identity has to
    follow the version that is now live, the way publishing already does."""

    def _two_versions(self, client: TestClient) -> None:
        response = client.post(
            "/components",
            json={
                "name": "Alpha Bot",
                "component_id": "bot",
                "component_type": "agent",
                "config": {"name": "Alpha Bot", "id": "bot", "description": "alpha desc", "metadata": {"tier": "one"}},
                "description": "alpha desc",
                "metadata": {"tier": "one"},
                "stage": "published",
            },
        )
        assert response.status_code == 201, response.text
        response = client.post(
            "/components/bot/configs",
            json={
                "config": {"name": "Beta Bot", "id": "bot", "description": "beta desc", "metadata": {"tier": "two"}},
                "stage": "published",
            },
        )
        assert response.status_code == 201, response.text

    def test_set_current_route_reprojects(self, db):
        client = make_client(db)
        self._two_versions(client)

        response = client.post("/components/bot/configs/1/set-current")
        assert response.status_code == 200, response.text

        assert response.json()["name"] == "Alpha Bot"
        assert response.json()["metadata"] == {"tier": "one"}
        row = db.get_component("bot")
        assert (row["name"], row["description"], row["metadata"]) == ("Alpha Bot", "alpha desc", {"tier": "one"})

    def test_patch_current_version_reprojects(self, db):
        client = make_client(db)
        self._two_versions(client)

        response = client.patch("/components/bot", json={"current_version": 1})
        assert response.status_code == 200, response.text

        assert response.json()["name"] == "Alpha Bot"
        row = db.get_component("bot")
        assert (row["name"], row["metadata"]) == ("Alpha Bot", {"tier": "one"})

    def test_explicit_fields_win_over_the_projection(self, db):
        client = make_client(db)
        self._two_versions(client)

        response = client.patch("/components/bot", json={"current_version": 1, "name": "Chosen Name"})
        assert response.status_code == 200, response.text

        row = db.get_component("bot")
        assert row["name"] == "Chosen Name"
        # The fields the request did not set still follow the live version.
        assert row["metadata"] == {"tier": "one"}

    def test_a_refused_pointer_move_projects_nothing(self, db):
        client = make_client(db)
        self._two_versions(client)

        response = client.post("/components/bot/configs/1/set-current", json={"guard": {"current_version": 99}})
        assert response.status_code == 409, response.text

        row = db.get_component("bot")
        assert (row["name"], row["current_version"]) == ("Beta Bot", 2)


class TestScopedConflictDetail:
    """A scoped caller must not learn another owner's ids - and must still be
    told the real cause, which for three of the five raise sites is a child,
    not a dependent."""

    def test_restore_blocked_by_an_archived_child_keeps_its_remedy(self, db):
        db.create_component_with_config(
            component_id="child",
            component_type=ComponentType.AGENT,
            name="child",
            config={"id": "child"},
            stage="published",
            user_id="user-a",
        )
        db.create_component_with_config(
            component_id="parent",
            component_type=ComponentType.TEAM,
            name="parent",
            config={"id": "parent"},
            stage="published",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "child",
                    "child_version": 1,
                    "position": 0,
                }
            ],
            user_id="user-a",
        )
        assert db.delete_component("parent", user_id="user-a") is True
        assert db.delete_component("child", user_id="user-a") is True

        response = make_client(db, user_id="user-a").post("/components/parent/restore")

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "Restore them first" in detail
        assert "child" in detail

    def test_publish_blocked_by_a_draft_child_keeps_its_remedy(self, db):
        db.create_component_with_config(
            component_id="kid",
            component_type=ComponentType.AGENT,
            name="kid",
            config={"id": "kid"},
            stage="published",
            user_id="user-a",
        )
        db.upsert_config(component_id="kid", config={"id": "kid"}, stage="draft")
        db.create_component_with_config(
            component_id="par",
            component_type=ComponentType.TEAM,
            name="par",
            config={"id": "par"},
            stage="draft",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "kid",
                    "child_version": 2,
                    "position": 0,
                }
            ],
            user_id="user-a",
        )

        response = make_client(db, user_id="user-a").patch("/components/par/configs/1", json={"stage": "published"})

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "publish the child first" in detail
        assert "kid" in detail

    def test_delete_blocked_by_a_dependent_keeps_the_version_it_names(self, db):
        db.create_component_with_config(
            component_id="shared",
            component_type=ComponentType.AGENT,
            name="shared",
            config={"id": "shared"},
            stage="published",
            user_id="user-a",
        )
        db.upsert_config(component_id="shared", config={"id": "shared"}, stage="draft")
        db.create_component_with_config(
            component_id="holder",
            component_type=ComponentType.TEAM,
            name="holder",
            config={"id": "holder"},
            stage="draft",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "shared",
                    "child_version": 2,
                    "position": 0,
                }
            ],
            user_id="user-a",
        )

        response = make_client(db, user_id="user-a").request("DELETE", "/components/shared/configs/2")

        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "v2" in detail
        assert "holder" in detail

    def test_a_foreign_dependent_does_not_veto_the_owners_delete(self, db):
        """Publishing shares a component for composing, so any other tenant can
        pin it -- from a draft this owner can never see, edit or reach. Letting
        such a parent block would hand every tenant a permanent veto over
        another tenant's own component, with the blocking id redacted out of
        the message and no surface to clear it from.
        """
        db.create_component_with_config(
            component_id="mine",
            component_type=ComponentType.AGENT,
            name="mine",
            config={"id": "mine"},
            stage="published",
            user_id="user-a",
        )
        db.create_component_with_config(
            component_id="their-secret-team",
            component_type=ComponentType.TEAM,
            name="their-secret-team",
            config={"id": "their-secret-team"},
            stage="draft",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "mine",
                    "child_version": 1,
                    "position": 0,
                }
            ],
            user_id="user-b",
        )

        response = make_client(db, user_id="user-a").delete("/components/mine")

        assert response.status_code == 204, response.text
        assert db.get_component("mine", user_id="user-a") is None

    def test_the_owners_own_dependent_still_vetoes(self, db):
        """The scope removes parents the caller cannot act on, not the guard."""
        db.create_component_with_config(
            component_id="mine",
            component_type=ComponentType.AGENT,
            name="mine",
            config={"id": "mine"},
            stage="published",
            user_id="user-a",
        )
        db.create_component_with_config(
            component_id="my-team",
            component_type=ComponentType.TEAM,
            name="my-team",
            config={"id": "my-team"},
            stage="draft",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "mine",
                    "child_version": 1,
                    "position": 0,
                }
            ],
            user_id="user-a",
        )

        response = make_client(db, user_id="user-a").delete("/components/mine")

        assert response.status_code == 409, response.text
        # The caller owns the blocker, so it is named: it can go and clear it.
        assert "my-team" in response.json()["detail"]

    def test_a_shared_dependent_still_vetoes(self, db):
        """An unowned parent is visible and editable by everyone, so it keeps
        its veto."""
        db.create_component_with_config(
            component_id="mine",
            component_type=ComponentType.AGENT,
            name="mine",
            config={"id": "mine"},
            stage="published",
            user_id="user-a",
        )
        db.create_component_with_config(
            component_id="shared-team",
            component_type=ComponentType.TEAM,
            name="shared-team",
            config={"id": "shared-team"},
            stage="draft",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "mine",
                    "child_version": 1,
                    "position": 0,
                }
            ],
        )

        response = make_client(db, user_id="user-a").delete("/components/mine")

        assert response.status_code == 409, response.text

    def test_an_admin_still_gets_every_id(self, db):
        db.create_component_with_config(
            component_id="mine",
            component_type=ComponentType.AGENT,
            name="mine",
            config={"id": "mine"},
            stage="published",
            user_id="user-a",
        )
        db.create_component_with_config(
            component_id="their-team",
            component_type=ComponentType.TEAM,
            name="their-team",
            config={"id": "their-team"},
            stage="published",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "mine",
                    "child_version": 1,
                    "position": 0,
                }
            ],
            user_id="user-b",
        )

        response = make_client(db).delete("/components/mine")

        assert response.status_code == 409, response.text
        assert "their-team" in response.json()["detail"]
