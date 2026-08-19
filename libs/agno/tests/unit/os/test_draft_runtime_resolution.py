"""Draft components are inert on dispatch surfaces; preview is owner-gated.

The Studio 3.0 dispatch contract:
- Unversioned resolution on a dispatch surface resolves only a published
  version; a draft-only component is readable and editable but not runnable.
- An explicit draft version is a control-plane preview: allowed for the
  owner and unscoped callers (admin, or authorization off), the same 404 as
  "not found" for everyone else. Published pins are never gated.
- Detail and run-lifecycle surfaces keep seeing drafts.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agno.agent.agent import get_agent_by_id as get_agent_by_id_db
from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.utils import allow_draft_preview
from agno.registry import Registry
from agno.tools.studio_runner import StudioRunnerTools


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="draft-resolution-db", db_file=str(tmp_path / "draft_resolution.db"))


def _mk(db, component_id, stage, user_id=None, extra=None):
    config = {"name": component_id, "instructions": "hi"}
    if extra:
        config.update(extra)
    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.AGENT,
        name=component_id,
        config=config,
        stage=stage,
        user_id=user_id,
    )


class TestLoaderPublishedOnly:
    def test_draft_only_component_is_not_loadable_by_default(self, db):
        _mk(db, "draft-bot", "draft")
        assert get_agent_by_id_db(db=db, id="draft-bot") is None

    def test_published_only_false_reaches_the_draft(self, db):
        _mk(db, "draft-bot", "draft")
        agent = get_agent_by_id_db(db=db, id="draft-bot", published_only=False)
        assert agent is not None

    def test_unversioned_load_takes_current_not_latest_draft(self, db):
        _mk(db, "mixed-bot", "published")
        db.upsert_config("mixed-bot", config={"name": "mixed-bot", "instructions": "draft v2"})
        agent = get_agent_by_id_db(db=db, id="mixed-bot")
        assert agent is not None
        assert agent.instructions == "hi"

    def test_explicit_version_bypasses_published_only(self, db):
        _mk(db, "pinned-bot", "published")
        db.upsert_config("pinned-bot", config={"name": "pinned-bot", "instructions": "draft v2"})
        agent = get_agent_by_id_db(db=db, id="pinned-bot", version=2)
        assert agent is not None
        assert agent.instructions == "draft v2"


class TestRunnerDispatch:
    def _runner(self, db):
        registry = Registry(name="r", dbs=[db])
        return StudioRunnerTools(registry=registry, db=db, include_all_components=True)

    def test_draft_only_component_is_not_dispatchable(self, db):
        from agno.tools.studio_runner import ComponentNotPublishedError

        _mk(db, "draft-bot", "draft")
        runner = self._runner(db)
        # Not a silent miss: the refusal names the real reason (unpublished),
        # not the registry, so a caller knows to publish or preview by version.
        with pytest.raises(ComponentNotPublishedError, match="no published version"):
            runner._agent_for_run("draft-bot")

    def test_dispatch_resolves_current_not_latest_draft(self, db):
        _mk(db, "mixed-bot", "published")
        db.upsert_config("mixed-bot", config={"name": "mixed-bot", "instructions": "draft v2"})
        runner = self._runner(db)
        agent = runner._agent_for_run("mixed-bot")
        assert agent is not None
        assert agent.instructions == "hi"

    def test_edit_base_still_reaches_the_draft(self, db):
        _mk(db, "mixed-bot", "published")
        db.upsert_config("mixed-bot", config={"name": "mixed-bot", "instructions": "draft v2"})
        runner = self._runner(db)
        agent = runner._load_agent_from_db("mixed-bot", version=2)
        assert agent is not None
        assert agent.instructions == "draft v2"


class TestPreviewGate:
    def test_no_version_is_never_gated(self, db):
        _mk(db, "any-bot", "draft", user_id="alice")
        assert allow_draft_preview(db, "any-bot", None, "bob") is True

    def test_published_pin_is_never_gated(self, db):
        _mk(db, "pub-bot", "published", user_id="alice")
        assert allow_draft_preview(db, "pub-bot", 1, "bob") is True

    def test_draft_preview_allowed_for_owner_and_privileged(self, db):
        _mk(db, "draft-bot", "draft", user_id="alice")
        assert allow_draft_preview(db, "draft-bot", 1, "alice") is True
        # Privilege (admin scope, or auth off) is explicit; a bare None actor
        # is an authenticated caller without a usable identity and is denied -
        # user_isolation=False widens reads, not the right to run drafts.
        assert allow_draft_preview(db, "draft-bot", 1, None, privileged=True) is True
        assert allow_draft_preview(db, "draft-bot", 1, None) is False

    def test_draft_preview_denied_for_other_scoped_user(self, db):
        _mk(db, "draft-bot", "draft", user_id="alice")
        assert allow_draft_preview(db, "draft-bot", 1, "bob") is False

    def test_shared_draft_denied_for_scoped_user(self, db):
        _mk(db, "shared-draft", "draft")
        assert allow_draft_preview(db, "shared-draft", 1, "carol") is False

    def test_missing_config_is_not_gated_here(self, db):
        _mk(db, "solo", "published")
        assert allow_draft_preview(db, "solo", 99, "bob") is True


class TestRestSurfaces:
    @pytest.fixture
    def client(self, db):
        agent_os = AgentOS(db=db, registry=Registry(name="r", dbs=[db]), telemetry=False)
        return TestClient(agent_os.get_app())

    def test_unversioned_run_of_a_draft_only_component_404s(self, db, client):
        _mk(db, "draft-bot", "draft")
        r = client.post("/agents/draft-bot/runs", data={"message": "hi", "stream": "false"})
        assert r.status_code == 404, (r.status_code, r.text)

    def test_detail_read_still_shows_the_draft(self, db, client):
        _mk(db, "draft-bot", "draft")
        r = client.get("/agents/draft-bot")
        assert r.status_code == 200, (r.status_code, r.text)

    def test_component_routes_still_show_the_draft(self, db, client):
        _mk(db, "draft-bot", "draft")
        r = client.get("/components/draft-bot")
        assert r.status_code == 200, (r.status_code, r.text)


def _scoped_app(db, user_id):
    """An AgentOS whose requests carry a scoped, non-privileged identity."""
    agent_os = AgentOS(db=db, registry=Registry(name="r", dbs=[db]), telemetry=False)
    app = agent_os.get_app()

    class _Scope(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user_id = user_id
            request.state.scopes = ["workflows:read", "agents:read", "teams:read", "components:read"]
            request.state.user_isolation_enabled = True
            request.state.authorization_enabled = False
            return await call_next(request)

    app.add_middleware(_Scope)
    return TestClient(app)


def _mk_workflow(db, component_id, user_id, description, stage):
    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.WORKFLOW,
        name=component_id,
        description=description,
        config={"name": component_id, "description": description, "steps": []},
        stage=stage,
        user_id=user_id,
    )


class TestVersionPinnedDetailRoute:
    """The one read route that takes a version must gate it like the run routes.

    Share-on-publish makes a published component readable by everyone, so a
    detail route that honours an explicit version without the preview gate
    hands out the owner's unpublished drafts.
    """

    def test_owner_may_pin_their_own_draft(self, db):
        _mk_workflow(db, "wf", "alice", "v1 public", "published")
        db.upsert_config("wf", config={"name": "wf", "description": "SECRET draft", "steps": []})
        r = _scoped_app(db, "alice").get("/workflows/wf", params={"version": 2})
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["description"] == "SECRET draft"

    def test_non_owner_still_reads_the_published_version(self, db):
        _mk_workflow(db, "wf", "alice", "v1 public", "published")
        db.upsert_config("wf", config={"name": "wf", "description": "SECRET draft", "steps": []})
        r = _scoped_app(db, "bob").get("/workflows/wf")
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["description"] == "v1 public"

    def test_non_owner_cannot_pin_the_owners_draft(self, db):
        _mk_workflow(db, "wf", "alice", "v1 public", "published")
        db.upsert_config("wf", config={"name": "wf", "description": "SECRET draft", "steps": []})
        r = _scoped_app(db, "bob").get("/workflows/wf", params={"version": 2})
        assert r.status_code == 404, (r.status_code, r.text)
        assert "SECRET draft" not in r.text

    def test_non_owner_may_still_pin_a_published_version(self, db):
        _mk_workflow(db, "wf", "alice", "v1 public", "published")
        db.upsert_config("wf", config={"name": "wf", "description": "v2 public", "steps": []}, stage="published")
        r = _scoped_app(db, "bob").get("/workflows/wf", params={"version": 1})
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json()["description"] == "v1 public"
