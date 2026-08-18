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
