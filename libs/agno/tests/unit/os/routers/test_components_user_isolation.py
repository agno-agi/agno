"""Integration tests for per-user component isolation.

Validates that:
- Isolation is asymmetric by design: writes are owner-scoped always, while
  reads scope on *stage*. A draft is the owner's alone; publishing puts a
  component on the platform, so a published row reads, runs and composes
  across owners, and archiving withdraws it again.
- Read tests pin both halves -- a foreign draft invisible, a foreign published
  component visible -- because a gate that refuses everything passes the first
  half on its own.
- Refusals split on what the caller can already see, so no refusal is an
  existence oracle: an invisible component answers the same 404 a missing id
  answers; a visible one gets an honest 403 naming the obstacle.
- Users cannot reference another user's draft as a team member or workflow
  step, at any nesting depth; a published component composes.

Component persistence is implemented by the SQLite and Postgres adapters; these
tests run against the SqliteDb-backed ``shared_db``.
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

JWT_SECRET = "test-secret-for-isolation"
TEST_OS_ID = "test-isolation-os"


def create_token(user_id: str, scopes: list[str] | None = None) -> str:
    """Create a JWT token for the given user.

    Default scopes cover the component endpoints (read / write / delete) plus the
    routes that resolve them. Pass ``scopes=[...]`` explicitly to test narrower-scope behaviour.
    """
    payload = {
        "sub": user_id,
        "aud": TEST_OS_ID,
        "scopes": scopes
        or [
            "components:read",
            "components:write",
            "components:delete",
            "agents:read",
            "agents:run",
            "teams:read",
            "teams:run",
            "workflows:read",
            "workflows:run",
        ],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def create_admin_token(user_id: str = "admin-user") -> str:
    """Create a JWT token with admin scope."""
    return create_token(user_id, scopes=["agent_os:admin"])


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_component(client, token: str, name: str, component_type: str, config: dict, stage: str = "published"):
    """Create a component over the API as the token's owner.

    Defaults to published -- on the platform for everyone. Pass ``stage="draft"``
    for the owner-private case.
    """
    return client.post(
        "/components",
        json={"name": name, "component_type": component_type, "config": config, "stage": stage},
        headers=auth_header(token),
    )


# The gate tests 404 before a model is reached, so only the owner-can-run tests need a real one.
RUNNABLE_MODEL = {"name": "OpenAIResponses", "id": "gpt-5.5", "provider": "OpenAI"}


@pytest.fixture
def shared_db(tmp_path):
    """A SqliteDb of this test's own.

    This suite is the only coverage of the component write routes' 403 layer,
    so it lives under tests/unit where the PR gate runs it; the fixture it
    used to inherit from the integration conftest is inlined here.
    """
    return SqliteDb(db_file=str(tmp_path / "isolation.db"))


@pytest.fixture
def client(shared_db):
    """Isolation-enabled client backed by ``shared_db``.

    No code-defined components are registered, so every component the routes return is DB-backed.
    """
    agent_os = AgentOS(
        id=TEST_OS_ID,
        db=shared_db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=True,
        ),
    )
    return TestClient(agent_os.get_app())


@pytest.fixture
def alice_agent(client):
    """A published agent component owned by ``user-a``: on the platform."""
    resp = create_component(
        client, create_token("user-a"), "Alice Agent", "agent", {"name": "Alice Agent", "instructions": "private"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["component_id"]


@pytest.fixture
def alice_draft(client):
    """A draft-only agent component owned by ``user-a``: owner-private."""
    resp = create_component(
        client,
        create_token("user-a"),
        "Alice Draft",
        "agent",
        {"name": "Alice Draft", "instructions": "private"},
        stage="draft",
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["component_id"]


@pytest.fixture
def shared_component(shared_db):
    """A component with no owner (predates isolation): readable under any scope, writable by none but admin.

    Seeded straight into the DB because the create route always stamps the caller as owner.
    """
    shared_db.create_component_with_config(
        component_id="shared_component",
        component_type=ComponentType.AGENT,
        name="Shared Component",
        config={"name": "Shared Component"},
        stage="published",
        user_id=None,
    )
    return "shared_component"


def _component_state(client, component_id: str) -> dict:
    """The owner's full view of a component: row plus config history.

    Captured before and after a refused foreign write, so the refusal is
    proven to have mutated nothing -- a 4xx alone cannot tell a clean refusal
    from the check-then-write shape that refuses AFTER the write landed.
    """
    token = create_token("user-a")
    row = client.get(f"/components/{component_id}", headers=auth_header(token))
    configs = client.get(f"/components/{component_id}/configs", headers=auth_header(token))
    assert row.status_code == 200
    assert configs.status_code == 200
    return {"row": row.json(), "configs": configs.json()}


# --- Component isolation ---


class TestComponentIsolation:
    """Verify that component endpoints scope reads by stage and writes by owner."""

    def test_list_hides_another_owners_draft(self, client, alice_draft):
        create_component(client, create_token("user-b"), "Bob Agent", "agent", {"name": "Bob Agent"})

        resp = client.get("/components", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 200
        assert alice_draft not in [c["component_id"] for c in resp.json()["data"]]

    def test_list_includes_another_owners_published_component(self, client, alice_agent):
        create_component(client, create_token("user-b"), "Bob Agent", "agent", {"name": "Bob Agent"})

        resp = client.get("/components", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 200
        assert alice_agent in [c["component_id"] for c in resp.json()["data"]]

    def test_admin_sees_all_components(self, client, alice_draft):
        """Admin should see components from all users, drafts included."""
        create_component(client, create_token("user-b"), "Bob Agent", "agent", {"name": "Bob Agent"})

        resp = client.get("/components", headers=auth_header(create_admin_token()))
        assert resp.status_code == 200
        assert resp.json()["meta"]["total_count"] == 2

    def test_owner_is_recorded_on_create(self, client, alice_agent):
        resp = client.get(f"/components/{alice_agent}", headers=auth_header(create_token("user-a")))
        assert resp.json()["user_id"] == "user-a"

    def test_get_by_id_follows_stage(self, client, alice_agent, alice_draft):
        """A foreign draft answers 404; a foreign published component reads."""
        token = create_token("user-b")
        assert client.get(f"/components/{alice_draft}", headers=auth_header(token)).status_code == 404
        assert client.get(f"/components/{alice_agent}", headers=auth_header(token)).status_code == 200

        # and the owner reads both
        owner = create_token("user-a")
        assert client.get(f"/components/{alice_draft}", headers=auth_header(owner)).status_code == 200
        assert client.get(f"/components/{alice_agent}", headers=auth_header(owner)).status_code == 200

    def test_user_cannot_update_other_users_component(self, client, alice_agent, alice_draft):
        """A foreign published component refuses with 403; a foreign draft answers 404. Neither mutates."""
        token = create_token("user-b")
        resp = client.patch(f"/components/{alice_agent}", json={"name": "hacked"}, headers=auth_header(token))
        assert resp.status_code == 403
        assert "another user" in resp.json()["detail"]

        resp = client.patch(f"/components/{alice_draft}", json={"name": "hacked"}, headers=auth_header(token))
        assert resp.status_code == 404

        owner = create_token("user-a")
        assert client.get(f"/components/{alice_agent}", headers=auth_header(owner)).json()["name"] == "Alice Agent"
        assert client.get(f"/components/{alice_draft}", headers=auth_header(owner)).json()["name"] == "Alice Draft"

    def test_user_cannot_delete_other_users_component(self, client, alice_agent, alice_draft):
        """A foreign published component refuses with 403; a foreign draft answers 404. Both survive."""
        token = create_token("user-b")
        assert client.delete(f"/components/{alice_agent}", headers=auth_header(token)).status_code == 403
        assert client.delete(f"/components/{alice_draft}", headers=auth_header(token)).status_code == 404

        owner = create_token("user-a")
        assert client.get(f"/components/{alice_agent}", headers=auth_header(owner)).status_code == 200
        assert client.get(f"/components/{alice_draft}", headers=auth_header(owner)).status_code == 200

    @pytest.mark.parametrize(
        "method,path",
        [
            ("POST", "/components/{cid}/configs"),
            ("PATCH", "/components/{cid}/configs/1"),
            ("DELETE", "/components/{cid}/configs/1"),
            ("POST", "/components/{cid}/configs/1/set-current"),
        ],
    )
    def test_config_writes_on_anothers_published_component_refuse(self, client, alice_agent, method, path):
        """Every config write route refuses a foreign published component with 403 and mutates nothing."""
        before = _component_state(client, alice_agent)

        resp = client.request(
            method, path.format(cid=alice_agent), json={"config": {}}, headers=auth_header(create_token("user-b"))
        )
        assert resp.status_code == 403
        assert "another user" in resp.json()["detail"]

        assert _component_state(client, alice_agent) == before

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/components/{cid}/configs"),
            ("POST", "/components/{cid}/configs"),
            ("PATCH", "/components/{cid}/configs/1"),
            ("GET", "/components/{cid}/configs/current"),
            ("GET", "/components/{cid}/configs/1"),
            ("DELETE", "/components/{cid}/configs/1"),
            ("POST", "/components/{cid}/configs/1/set-current"),
        ],
    )
    def test_config_routes_on_anothers_draft_component_answer_404(self, client, alice_draft, method, path):
        """A foreign draft component is invisible: every config route answers 404."""
        resp = client.request(
            method, path.format(cid=alice_draft), json={"config": {}}, headers=auth_header(create_token("user-b"))
        )
        assert resp.status_code == 404

    def test_config_reads_on_anothers_published_component_serve_published_depth(self, client, alice_agent):
        """A non-owner reads the published stage only: drafts above the live pointer stay the owner's."""
        owner = create_token("user-a")
        draft = client.post(
            f"/components/{alice_agent}/configs",
            json={"config": {"name": "Alice Agent", "instructions": "wip"}, "stage": "draft"},
            headers=auth_header(owner),
        )
        assert draft.status_code == 201, draft.text
        draft_version = draft.json()["version"]

        token = create_token("user-b")
        listing = client.get(f"/components/{alice_agent}/configs", headers=auth_header(token))
        assert listing.status_code == 200
        assert {c["stage"] for c in listing.json()} == {"published"}

        assert client.get(f"/components/{alice_agent}/configs/current", headers=auth_header(token)).status_code == 200
        assert client.get(f"/components/{alice_agent}/configs/1", headers=auth_header(token)).status_code == 200
        # The draft version answers as if absent, so the 404 cannot be read as "exists but withheld".
        assert (
            client.get(f"/components/{alice_agent}/configs/{draft_version}", headers=auth_header(token)).status_code
            == 404
        )
        # while the owner reads it
        assert (
            client.get(f"/components/{alice_agent}/configs/{draft_version}", headers=auth_header(owner)).status_code
            == 200
        )

    def test_owner_writes_own_configs(self, client, alice_agent):
        """The owner scope must not block a legitimate write to one's own component."""
        owner = create_token("user-a")
        created = client.post(
            f"/components/{alice_agent}/configs",
            json={"config": {"name": "Alice Agent", "instructions": "v2"}, "stage": "published"},
            headers=auth_header(owner),
        )
        assert created.status_code == 201, created.text
        version = created.json()["version"]

        rollback = client.post(f"/components/{alice_agent}/configs/1/set-current", headers=auth_header(owner))
        assert rollback.status_code == 200, rollback.text
        assert rollback.json()["current_version"] == 1

        restored = client.post(f"/components/{alice_agent}/configs/{version}/set-current", headers=auth_header(owner))
        assert restored.status_code == 200, restored.text
        assert restored.json()["current_version"] == version

    def test_component_id_clash_does_not_confirm_other_users_component(self, client, alice_agent):
        """Claiming a taken id must not reveal that another user owns it."""
        resp = client.post(
            "/components",
            json={
                "component_id": alice_agent,
                "name": "squat",
                "component_type": "agent",
                "config": {"name": "squat"},
            },
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 400
        assert "already exists" not in resp.text

    def test_same_name_for_two_users_does_not_collide(self, client):
        """Two users may create a component with the same name."""
        resp_a = create_component(client, create_token("user-a"), "Shared Name", "agent", {"name": "Shared Name"})
        resp_b = create_component(client, create_token("user-b"), "Shared Name", "agent", {"name": "Shared Name"})

        assert resp_a.status_code == 201
        assert resp_b.status_code == 201
        assert resp_a.json()["component_id"] != resp_b.json()["component_id"]


# --- Shared (unowned) component writes ---


class TestSharedComponentWrites:
    """A shared component is readable under scope but not writable: 403, not 404.

    A 404 would be pointless here -- the caller can already GET the component and see it
    in the listing -- and diverges from the 403 every sibling domain returns for shared content.
    """

    def test_scoped_user_can_read_shared_component(self, client, shared_component):
        resp = client.get(f"/components/{shared_component}", headers=auth_header(create_token("user-a")))
        assert resp.status_code == 200

    def test_scoped_user_cannot_patch_shared_component(self, client, shared_component):
        resp = client.patch(
            f"/components/{shared_component}", json={"name": "x"}, headers=auth_header(create_token("user-a"))
        )
        assert resp.status_code == 403
        assert "shared" in resp.json()["detail"].lower()

    def test_scoped_user_cannot_delete_shared_component(self, client, shared_component):
        resp = client.delete(f"/components/{shared_component}", headers=auth_header(create_token("user-a")))
        assert resp.status_code == 403

    @pytest.mark.parametrize(
        "method,path",
        [
            ("POST", "/components/{cid}/configs"),
            ("PATCH", "/components/{cid}/configs/1"),
            ("DELETE", "/components/{cid}/configs/1"),
            ("POST", "/components/{cid}/configs/1/set-current"),
        ],
    )
    def test_scoped_user_cannot_write_shared_component_configs(self, client, shared_component, method, path):
        """Every config write route refuses a shared component before touching its configs."""
        resp = client.request(
            method, path.format(cid=shared_component), json={"config": {}}, headers=auth_header(create_token("user-a"))
        )
        assert resp.status_code == 403

    def test_admin_can_modify_shared_component(self, client, shared_component):
        """Admin (unscoped) writes are unchanged: no 403."""
        resp = client.patch(
            f"/components/{shared_component}", json={"name": "renamed"}, headers=auth_header(create_admin_token())
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "renamed"


# --- Component resolution on the run routes ---


class TestComponentResolutionIsolation:
    """Routes resolving DB-backed components follow the same stage-scoped visibility."""

    def test_agent_listing_follows_stage(self, client, alice_agent, alice_draft):
        resp = client.get("/agents", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 200
        listed = [a["id"] for a in resp.json()]
        assert alice_draft not in listed
        assert alice_agent in listed

    def test_user_cannot_run_another_owners_draft_agent(self, client, alice_draft):
        resp = client.post(
            f"/agents/{alice_draft}/runs",
            data={"message": "hi", "stream": "false"},
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 404

    def test_running_another_owners_published_agent_passes_the_gate(self, client, alice_agent, monkeypatch):
        """Publishing shares the run surface: a non-owner's attempt answers exactly as the owner's.

        The API key is stripped so the modelless fixture's default model fails
        fast, client-side, identically for both callers -- no network and no
        paid calls on a keyed machine (an unresolvable model is no substitute:
        it fails rehydration and answers 404 for everyone, hiding the gate).
        The assertion is that the gate answers the non-owner the same as the
        owner, never the draft 404 or the write 403.
        """
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        as_owner = client.post(
            f"/agents/{alice_agent}/runs",
            data={"message": "hi", "stream": "false"},
            headers=auth_header(create_token("user-a")),
        )
        as_other = client.post(
            f"/agents/{alice_agent}/runs",
            data={"message": "hi", "stream": "false"},
            headers=auth_header(create_token("user-b")),
        )
        assert as_other.status_code == as_owner.status_code
        assert as_other.status_code not in (403, 404)

    def test_get_agent_follows_stage(self, client, alice_agent, alice_draft):
        token = create_token("user-b")
        assert client.get(f"/agents/{alice_draft}", headers=auth_header(token)).status_code == 404
        assert client.get(f"/agents/{alice_agent}", headers=auth_header(token)).status_code == 200

    @pytest.mark.parametrize(
        "path",
        [
            "/agents/{cid}/sessions/some-session/fork",
            "/agents/{cid}/runs/some-run/checkpoints?session_id=some-session",
            "/agents/{cid}/runs/some-run/checkpoints/0?session_id=some-session",
        ],
    )
    def test_agent_routes_do_not_leak_component_existence(self, client, alice_draft, path):
        """Another user's draft must answer exactly as a missing one -- otherwise it is an existence oracle."""
        token = create_token("user-b")
        method = "POST" if path.endswith("/fork") else "GET"

        owned = client.request(method, path.format(cid=alice_draft), headers=auth_header(token))
        missing = client.request(method, path.format(cid="no-such-component"), headers=auth_header(token))

        assert owned.status_code == missing.status_code
        assert owned.json() == missing.json()

    @pytest.mark.parametrize(
        "path",
        [
            "/teams/{cid}/sessions/some-session/fork",
            "/teams/{cid}/runs/some-run/checkpoints?session_id=some-session",
            "/teams/{cid}/runs/some-run/checkpoints/0?session_id=some-session",
        ],
    )
    def test_team_routes_do_not_leak_component_existence(self, client, path):
        """Team counterpart of the agent existence-oracle check."""
        resp = create_component(
            client, create_token("user-a"), "Alice Team", "team", {"name": "Alice Team", "members": []}, stage="draft"
        )
        alice_team = resp.json()["component_id"]
        token = create_token("user-b")
        method = "POST" if path.endswith("/fork") else "GET"

        owned = client.request(method, path.format(cid=alice_team), headers=auth_header(token))
        missing = client.request(method, path.format(cid="no-such-component"), headers=auth_header(token))

        assert owned.status_code == missing.status_code
        assert owned.json() == missing.json()


# --- Owner can run their own DB-backed components ---


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
class TestOwnerCanRunOwnComponents:
    """The isolation gate must block non-owners without breaking the owner.

    The 404 checks above cannot tell a correct denial from a route that is broken for
    everyone, so these run an owner's own components end-to-end against a real model.
    """

    def test_owner_can_run_own_agent(self, client):
        resp = create_component(
            client,
            create_token("user-a"),
            "Runnable Agent",
            "agent",
            {"name": "Runnable Agent", "model": RUNNABLE_MODEL, "instructions": "Reply with exactly: OK"},
        )
        assert resp.status_code == 201, resp.text
        agent_id = resp.json()["component_id"]

        run = client.post(
            f"/agents/{agent_id}/runs",
            data={"message": "ping", "stream": "false"},
            headers=auth_header(create_token("user-a")),
        )
        assert run.status_code == 200, run.text
        assert run.json()["content"] is not None

    def test_owner_can_run_own_team(self, client):
        member = create_component(
            client,
            create_token("user-a"),
            "Team Member",
            "agent",
            {"name": "Team Member", "model": RUNNABLE_MODEL, "instructions": "Reply with exactly: PONG"},
        )
        member_id = member.json()["component_id"]
        resp = create_component(
            client,
            create_token("user-a"),
            "Runnable Team",
            "team",
            {
                "name": "Runnable Team",
                "model": RUNNABLE_MODEL,
                "mode": "coordinate",
                "members": [{"type": "agent", "agent_id": member_id}],
                "instructions": "Delegate to your member and return its reply.",
            },
        )
        assert resp.status_code == 201, resp.text
        team_id = resp.json()["component_id"]

        # A team whose member fails to rehydrate still returns 200, so assert it resolved.
        detail = client.get(f"/teams/{team_id}", headers=auth_header(create_token("user-a")))
        assert detail.status_code == 200, detail.text
        assert member_id in [m.get("id") for m in detail.json().get("members", [])]

        run = client.post(
            f"/teams/{team_id}/runs",
            data={"message": "say the word", "stream": "false"},
            headers=auth_header(create_token("user-a")),
        )
        assert run.status_code == 200, run.text
        assert run.json()["content"] is not None

    def test_owner_can_run_own_workflow(self, client):
        executor = create_component(
            client,
            create_token("user-a"),
            "Step Executor",
            "agent",
            {"name": "Step Executor", "model": RUNNABLE_MODEL, "instructions": "Reply with exactly: DONE"},
        )
        executor_id = executor.json()["component_id"]
        resp = create_component(
            client,
            create_token("user-a"),
            "Runnable Workflow",
            "workflow",
            {"name": "Runnable Workflow", "steps": [{"type": "Step", "name": "s1", "agent_id": executor_id}]},
        )
        assert resp.status_code == 201, resp.text
        workflow_id = resp.json()["component_id"]

        run = client.post(
            f"/workflows/{workflow_id}/runs",
            data={"message": "go", "stream": "false"},
            headers=auth_header(create_token("user-a")),
        )
        assert run.status_code == 200, run.text
        assert run.json()["content"] is not None


# --- Referenced-component ownership ---


class TestReferencedComponentOwnership:
    """References follow visibility: a foreign draft cannot be referenced; a published one composes."""

    def test_team_member_reference_follows_stage(self, client, alice_agent, alice_draft):
        token = create_token("user-b")
        refused = create_component(
            client,
            token,
            "Bob Team Draft Ref",
            "team",
            {"name": "Bob Team Draft Ref", "members": [{"type": "agent", "agent_id": alice_draft}]},
        )
        assert refused.status_code == 404

        composed = create_component(
            client,
            token,
            "Bob Team",
            "team",
            {"name": "Bob Team", "members": [{"type": "agent", "agent_id": alice_agent}]},
        )
        assert composed.status_code == 201, composed.text

    def test_workflow_step_reference_follows_stage(self, client, alice_agent, alice_draft):
        token = create_token("user-b")
        refused = create_component(
            client,
            token,
            "Bob Workflow Draft Ref",
            "workflow",
            {"name": "Bob Workflow Draft Ref", "steps": [{"name": "s1", "agent_id": alice_draft}]},
        )
        assert refused.status_code == 404

        composed = create_component(
            client,
            token,
            "Bob Workflow",
            "workflow",
            {"name": "Bob Workflow", "steps": [{"name": "s1", "agent_id": alice_agent}]},
        )
        assert composed.status_code == 201, composed.text

    @pytest.mark.parametrize("container", ["Parallel", "Loop", "Condition", "Steps"])
    def test_cannot_hide_draft_reference_inside_a_step_container(self, client, alice_draft, container):
        """The reference walk must reach steps nested in any container type."""
        resp = create_component(
            client,
            create_token("user-b"),
            f"Bob {container}",
            "workflow",
            {
                "name": f"Bob {container}",
                "steps": [{"name": "c", "type": container, "steps": [{"name": "s", "agent_id": alice_draft}]}],
            },
        )
        assert resp.status_code == 404

    def test_cannot_smuggle_draft_reference_via_new_config_version(self, client, alice_agent, alice_draft):
        """The check applies to config updates, not just creation."""
        created = create_component(
            client, create_token("user-b"), "Bob Own", "workflow", {"name": "Bob Own", "steps": []}
        )
        bob_workflow = created.json()["component_id"]

        refused = client.post(
            f"/components/{bob_workflow}/configs",
            json={"config": {"name": "Bob Own", "steps": [{"name": "s", "agent_id": alice_draft}]}},
            headers=auth_header(create_token("user-b")),
        )
        assert refused.status_code == 404

        composed = client.post(
            f"/components/{bob_workflow}/configs",
            json={"config": {"name": "Bob Own", "steps": [{"name": "s", "agent_id": alice_agent}]}},
            headers=auth_header(create_token("user-b")),
        )
        assert composed.status_code == 201, composed.text

    def test_cannot_smuggle_draft_reference_via_explicit_link(self, client, alice_draft):
        created = create_component(
            client, create_token("user-b"), "Bob Linked", "workflow", {"name": "Bob Linked", "steps": []}
        )
        bob_workflow = created.json()["component_id"]

        resp = client.post(
            f"/components/{bob_workflow}/configs",
            json={
                "config": {"name": "Bob Linked"},
                "links": [
                    {
                        "link_kind": "member",
                        "link_key": "member_0",
                        "child_component_id": alice_draft,
                        "child_version": 1,
                    }
                ],
            },
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 404

    def test_owner_can_reference_own_component(self, client, alice_agent):
        """The check must not block a legitimate self-reference."""
        resp = create_component(
            client,
            create_token("user-a"),
            "Alice Team",
            "team",
            {"name": "Alice Team", "members": [{"type": "agent", "agent_id": alice_agent}]},
        )
        assert resp.status_code == 201

    def test_can_reference_shared_component(self, client, shared_component):
        """Referencing a shared (unowned) component must still succeed."""
        resp = create_component(
            client,
            create_token("user-b"),
            "Bob Uses Shared",
            "workflow",
            {"name": "Bob Uses Shared", "steps": [{"name": "s", "agent_id": shared_component}]},
        )
        assert resp.status_code == 201

    def test_draft_reference_refused_unresolvable_reference_allowed(self, client, alice_draft):
        """Another user's draft can't be referenced (404). An id that resolves to no DB row
        is allowed -- it may be a shared, code-defined component."""
        token = create_token("user-b")
        missing = client.post(
            "/components",
            json={
                "name": "Bob Missing Ref",
                "component_type": "workflow",
                "config": {"name": "Bob Missing Ref", "steps": [{"name": "s", "agent_id": "no-such-agent"}]},
            },
            headers=auth_header(token),
        )
        foreign = client.post(
            "/components",
            json={
                "name": "Bob Foreign Ref",
                "component_type": "workflow",
                "config": {"name": "Bob Foreign Ref", "steps": [{"name": "s", "agent_id": alice_draft}]},
            },
            headers=auth_header(token),
        )
        assert missing.status_code == 201  # unresolvable id may be code-defined -> allowed
        assert foreign.status_code == 404  # another user's draft -> refused


# --- Isolation disabled ---


class TestIsolationDisabled:
    """With user_isolation off, components stay global."""

    @pytest.fixture
    def open_client(self, shared_db):
        agent_os = AgentOS(
            id=TEST_OS_ID,
            db=shared_db,
            authorization=True,
            authorization_config=AuthorizationConfig(
                verification_keys=[JWT_SECRET],
                algorithm="HS256",
                user_isolation=False,
            ),
        )
        return TestClient(agent_os.get_app())

    def test_components_are_shared_when_isolation_is_off(self, open_client):
        resp = create_component(open_client, create_token("user-a"), "Shared Agent", "agent", {"name": "Shared Agent"})
        assert resp.status_code == 201
        component_id = resp.json()["component_id"]

        resp = open_client.get(f"/components/{component_id}", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 200
