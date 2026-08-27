"""A code-defined target is exempt from the draft-only schedule refusal.

The run routes resolve code-defined components from the in-process lists before
they consult the component catalog, so a code-defined target answers its run
endpoint even while a catalog row carrying the same id holds nothing but drafts.
Refusing that schedule blocks a target that would have worked, and names a
remedy ("publish it first") that would not change the run either way.

The evidence reaches the shared predicate as ``is_code_defined``. A caller that
holds no in-process lists passes nothing, and the catalog decides alone.
"""

import json
from types import SimpleNamespace

import pytest

from agno.agent import Agent
from agno.db.base import ComponentType
from agno.db.schemas.scheduler import Schedule
from agno.db.sqlite import SqliteDb
from agno.tools.scheduler import (
    SchedulerTools,
    adraft_endpoint_refusal,
    adraft_target_refusal,
    code_defined_probe,
    draft_endpoint_refusal,
    draft_target_refusal,
)


def _draft_only(db, component_id, component_type=ComponentType.AGENT, user_id=None):
    db.upsert_component(component_id=component_id, component_type=component_type, name=component_id, user_id=user_id)
    db.upsert_config(component_id, config={"name": component_id}, stage="draft")


def _archived(db, component_id, user_id=None):
    db.upsert_component(
        component_id=component_id, component_type=ComponentType.AGENT, name=component_id, user_id=user_id
    )
    db.delete_component(component_id)


def _create(tools, name, endpoint):
    return json.loads(tools.create_schedule(name=name, cron="0 9 * * *", endpoint=endpoint, payload='{"message": "x"}'))


async def _acreate(tools, name, endpoint):
    return json.loads(
        await tools.acreate_schedule(name=name, cron="0 9 * * *", endpoint=endpoint, payload='{"message": "x"}')
    )


class TestCodeDefinedProbe:
    """The probe answers per (type, id), reads its lists live, and abstains."""

    def test_no_lists_is_no_evidence(self):
        assert code_defined_probe() is None
        assert code_defined_probe(None, None, None) is None

    def test_an_empty_list_is_still_evidence(self):
        # The list is the channel; AgentOS fills its own after wiring
        probe = code_defined_probe(agents=[])
        assert probe is not None
        assert probe("agent", "anything") is False

    def test_answers_per_type_not_per_id(self):
        probe = code_defined_probe(agents=[SimpleNamespace(id="shared")])
        assert probe("agent", "shared") is True
        assert probe("team", "shared") is False
        assert probe("workflow", "shared") is False

    def test_every_type_has_its_own_list(self):
        probe = code_defined_probe(
            agents=[SimpleNamespace(id="a")],
            teams=[SimpleNamespace(id="t")],
            workflows=[SimpleNamespace(id="w")],
        )
        assert (probe("agent", "a"), probe("team", "t"), probe("workflow", "w")) == (True, True, True)
        assert probe("agent", "t") is False

    def test_the_list_is_read_at_probe_time(self):
        live: list = []
        probe = code_defined_probe(agents=live)
        assert probe("agent", "late") is False
        live.append(SimpleNamespace(id="late"))
        assert probe("agent", "late") is True

    def test_entries_without_an_id_are_ignored(self):
        probe = code_defined_probe(agents=[SimpleNamespace()])
        assert probe("agent", "anything") is False

    def test_an_unknown_target_type_never_matches(self):
        probe = code_defined_probe(agents=[SimpleNamespace(id="a")])
        assert probe("component", "a") is False


class TestSharedPredicateExemption:
    """The predicate itself, on both the endpoint and the schedule form."""

    @pytest.fixture
    def db(self, tmp_path):
        return SqliteDb(id="sched-code-defined-pred", db_file=str(tmp_path / "pred.db"))

    def test_endpoint_refusal_exempts_a_code_defined_target(self, db):
        _draft_only(db, "news-agent")
        assert draft_endpoint_refusal(db, "/agents/news-agent/runs") == ("agent", "news-agent")
        probe = code_defined_probe(agents=[SimpleNamespace(id="news-agent")])
        assert draft_endpoint_refusal(db, "/agents/news-agent/runs", is_code_defined=probe) is None

    @pytest.mark.asyncio
    async def test_aendpoint_refusal_exempts_a_code_defined_target(self, db):
        _draft_only(db, "news-agent")
        assert await adraft_endpoint_refusal(db, "/agents/news-agent/runs") == ("agent", "news-agent")
        probe = code_defined_probe(agents=[SimpleNamespace(id="news-agent")])
        assert await adraft_endpoint_refusal(db, "/agents/news-agent/runs", is_code_defined=probe) is None

    def test_target_refusal_exempts_a_code_defined_target(self, db):
        _draft_only(db, "news-agent")
        schedule = Schedule(
            id="s1", name="s1", endpoint="/agents/news-agent/runs", cron_expr="0 9 * * *", timezone="UTC"
        )
        assert draft_target_refusal(db, schedule) == ("agent", "news-agent")
        probe = code_defined_probe(agents=[SimpleNamespace(id="news-agent")])
        assert draft_target_refusal(db, schedule, is_code_defined=probe) is None

    @pytest.mark.asyncio
    async def test_atarget_refusal_exempts_a_code_defined_target(self, db):
        _draft_only(db, "news-agent")
        schedule = Schedule(
            id="s1", name="s1", endpoint="/agents/news-agent/runs", cron_expr="0 9 * * *", timezone="UTC"
        )
        assert await adraft_target_refusal(db, schedule) == ("agent", "news-agent")
        probe = code_defined_probe(agents=[SimpleNamespace(id="news-agent")])
        assert await adraft_target_refusal(db, schedule, is_code_defined=probe) is None

    def test_the_probe_is_consulted_before_the_catalog_is_read(self, db):
        # The exemption must not depend on - or disclose - a row the caller may
        # not see, so it is settled without reading the catalog at all
        reads = []

        class _RecordingDb(SqliteDb):
            def get_component(self, *args, **kwargs):
                reads.append(args)
                return super().get_component(*args, **kwargs)

        recording = _RecordingDb(id="sched-code-defined-reads", db_file=db.db_file)
        _draft_only(recording, "news-agent")
        reads.clear()
        probe = code_defined_probe(agents=[SimpleNamespace(id="news-agent")])
        assert draft_endpoint_refusal(recording, "/agents/news-agent/runs", is_code_defined=probe) is None
        assert reads == []


class TestCreateExemptsCodeDefinedTargets:
    """SchedulerTools.create_schedule, sync and async."""

    @pytest.fixture
    def db(self, tmp_path):
        return SqliteDb(id="sched-code-defined-create", db_file=str(tmp_path / "create.db"))

    @pytest.fixture
    def news_agent(self):
        return Agent(id="news-agent", name="News Agent")

    @pytest.fixture
    def tools(self, db, news_agent):
        return SchedulerTools(db=db, default_payload={"message": "go"}, include_agents=[news_agent])

    def test_code_defined_target_with_a_draft_row_is_scheduled(self, db, tools):
        _draft_only(db, "news-agent")
        out = _create(tools, "daily-news", "/agents/news-agent/runs")
        assert out.get("status") == "created", out

    @pytest.mark.asyncio
    async def test_acode_defined_target_with_a_draft_row_is_scheduled(self, db, tools):
        _draft_only(db, "news-agent")
        out = await _acreate(tools, "daily-news-async", "/agents/news-agent/runs")
        assert out.get("status") == "created", out

    def test_a_genuinely_draft_only_target_is_still_refused(self, db, tools):
        _draft_only(db, "db-only-agent")
        out = _create(tools, "armed-at-a-draft", "/agents/db-only-agent/runs")
        assert out.get("error_type") == "target_not_published", out
        assert out["target_type"] == "agent" and out["target_id"] == "db-only-agent"
        _, total = db.get_schedules()
        assert total == 0

    @pytest.mark.asyncio
    async def test_a_genuinely_draft_only_target_is_still_refused_async(self, db, tools):
        _draft_only(db, "db-only-agent")
        out = await _acreate(tools, "armed-at-a-draft-async", "/agents/db-only-agent/runs")
        assert out.get("error_type") == "target_not_published", out

    def test_without_the_lists_the_catalog_still_decides(self, db):
        # No in-process evidence: the toolkit cannot tell the two cases apart
        _draft_only(db, "news-agent")
        blind = SchedulerTools(db=db, default_payload={"message": "go"})
        out = _create(blind, "blind", "/agents/news-agent/runs")
        assert out.get("error_type") == "target_not_published", out

    def test_a_list_assigned_after_construction_is_honoured(self, db, news_agent):
        # The toolkit is usually built before the AgentOS whose lists it is given
        _draft_only(db, "news-agent")
        late = SchedulerTools(db=db, default_payload={"message": "go"})
        assert _create(late, "before", "/agents/news-agent/runs").get("error_type") == "target_not_published"
        late.include_agents = [news_agent]
        assert _create(late, "after", "/agents/news-agent/runs").get("status") == "created"

    def test_a_code_defined_agent_does_not_exempt_a_draft_team(self, db, tools):
        # Same id, different type: exempting the team would arm a schedule that
        # resolves to nothing
        _draft_only(db, "news-agent", component_type=ComponentType.TEAM)
        out = _create(tools, "wrong-type", "/teams/news-agent/runs")
        assert out.get("error_type") == "target_not_published", out
        assert out["target_type"] == "team"

    @pytest.mark.asyncio
    async def test_a_code_defined_agent_does_not_exempt_a_draft_team_async(self, db, tools):
        _draft_only(db, "news-agent", component_type=ComponentType.TEAM)
        out = await _acreate(tools, "wrong-type-async", "/teams/news-agent/runs")
        assert out.get("error_type") == "target_not_published", out

    def test_code_defined_teams_and_workflows_are_exempt_too(self, db):
        _draft_only(db, "crew", component_type=ComponentType.TEAM)
        _draft_only(db, "pipeline", component_type=ComponentType.WORKFLOW)
        tools = SchedulerTools(
            db=db,
            default_payload={"message": "go"},
            include_teams=[SimpleNamespace(id="crew")],
            include_workflows=[SimpleNamespace(id="pipeline")],
        )
        assert _create(tools, "crew-run", "/teams/crew/runs").get("status") == "created"
        assert _create(tools, "pipeline-run", "/workflows/pipeline/runs").get("status") == "created"

    def test_an_archived_code_defined_target_is_still_refused(self, db, tools):
        # Archived ids stay reserved: the catalog row is the tombstone, and a
        # code-defined component shadowing it must not re-arm the id
        _archived(db, "news-agent")
        out = _create(tools, "archived", "/agents/news-agent/runs")
        assert out.get("error_type") == "target_archived", out

    @pytest.mark.asyncio
    async def test_an_archived_code_defined_target_is_still_refused_async(self, db, tools):
        _archived(db, "news-agent")
        out = await _acreate(tools, "archived-async", "/agents/news-agent/runs")
        assert out.get("error_type") == "target_archived", out


class TestEnableExemptsCodeDefinedTargets:
    """SchedulerTools.enable_schedule, sync and async."""

    @pytest.fixture
    def db(self, tmp_path):
        return SqliteDb(id="sched-code-defined-enable", db_file=str(tmp_path / "enable.db"))

    @staticmethod
    def _armed(db, tools, name, endpoint):
        out = _create(tools, name, endpoint)
        assert out.get("status") == "created", out
        db.update_schedule(out["id"], enabled=False)
        return out["id"]

    def test_a_code_defined_target_re_arms(self, db):
        blind = SchedulerTools(db=db, default_payload={"message": "go"})
        sid = self._armed(db, blind, "news", "/agents/news-agent/runs")
        _draft_only(db, "news-agent")
        assert json.loads(blind.enable_schedule(sid)).get("error_type") == "target_not_published"
        tools = SchedulerTools(
            db=db, default_payload={"message": "go"}, include_agents=[SimpleNamespace(id="news-agent")]
        )
        out = json.loads(tools.enable_schedule(sid))
        assert out.get("status") == "enabled", out

    @pytest.mark.asyncio
    async def test_a_code_defined_target_re_arms_async(self, db):
        blind = SchedulerTools(db=db, default_payload={"message": "go"})
        sid = self._armed(db, blind, "news-async", "/agents/news-agent/runs")
        _draft_only(db, "news-agent")
        assert json.loads(await blind.aenable_schedule(sid)).get("error_type") == "target_not_published"
        tools = SchedulerTools(
            db=db, default_payload={"message": "go"}, include_agents=[SimpleNamespace(id="news-agent")]
        )
        out = json.loads(await tools.aenable_schedule(sid))
        assert out.get("status") == "enabled", out

    def test_a_genuinely_draft_only_target_still_refuses_to_re_arm(self, db):
        tools = SchedulerTools(
            db=db, default_payload={"message": "go"}, include_agents=[SimpleNamespace(id="news-agent")]
        )
        sid = self._armed(db, tools, "db-only", "/agents/db-only-agent/runs")
        _draft_only(db, "db-only-agent")
        out = json.loads(tools.enable_schedule(sid))
        assert out.get("error_type") == "target_not_published", out

    @pytest.mark.asyncio
    async def test_a_genuinely_draft_only_target_still_refuses_to_re_arm_async(self, db):
        tools = SchedulerTools(
            db=db, default_payload={"message": "go"}, include_agents=[SimpleNamespace(id="news-agent")]
        )
        sid = self._armed(db, tools, "db-only-async", "/agents/db-only-agent/runs")
        _draft_only(db, "db-only-agent")
        out = json.loads(await tools.aenable_schedule(sid))
        assert out.get("error_type") == "target_not_published", out


class TestOwnerScopingSurvivesTheExemption:
    """The exemption adds no disclosure and removes no scoping."""

    @pytest.fixture
    def db(self, tmp_path):
        return SqliteDb(id="sched-code-defined-scope", db_file=str(tmp_path / "scope.db"))

    @staticmethod
    def _tools(db, owner, include_agents=None):
        return SchedulerTools(db=db, user_id=owner, default_payload={"message": "go"}, include_agents=include_agents)

    def test_another_owners_draft_row_is_still_not_reported(self, db):
        _draft_only(db, "their-draft", user_id="other-owner")
        out = _create(self._tools(db, "scoped-owner", include_agents=[]), "invisible", "/agents/their-draft/runs")
        assert out.get("status") == "created", out
        assert "published" not in json.dumps(out)

    def test_the_callers_own_draft_row_is_still_refused(self, db):
        _draft_only(db, "my-draft", user_id="scoped-owner")
        out = _create(self._tools(db, "scoped-owner", include_agents=[]), "mine", "/agents/my-draft/runs")
        assert out.get("error_type") == "target_not_published", out

    def test_a_shared_unowned_draft_row_is_still_refused(self, db):
        _draft_only(db, "shared-draft")
        out = _create(self._tools(db, "scoped-owner", include_agents=[]), "shared", "/agents/shared-draft/runs")
        assert out.get("error_type") == "target_not_published", out


class TestTheDeploymentActuallyWiresTheProbe:
    """The exemption is only real if the lists reach the router.

    Every refusal builds its probe from the lists it was constructed with, so
    an AgentOS that omits them refuses a code-defined target on all three
    schedule surfaces -- and the remedy it names ("publish it first") would
    not change how the run resolves. These pin the wiring, not the predicate.
    """

    @pytest.fixture
    def wired(self, tmp_path):
        from agno.os import AgentOS
        from agno.registry import Registry

        db = SqliteDb(id="wire-db", db_file=str(tmp_path / "wire.db"))
        agent = Agent(id="news-agent", name="News")
        agent_os = AgentOS(db=db, agents=[agent], registry=Registry(name="r", dbs=[db]), telemetry=False)
        return db, agent_os

    def test_create_allows_a_schedule_on_a_code_defined_target(self, wired):
        from fastapi.testclient import TestClient

        db, agent_os = wired
        _draft_only(db, "news-agent")
        client = TestClient(agent_os.get_app())
        r = client.post(
            "/schedules",
            json={"name": "nightly", "endpoint": "/agents/news-agent/runs", "cron_expr": "0 0 * * *"},
        )
        assert r.status_code == 201, (r.status_code, r.text)

    def test_a_catalog_only_draft_target_is_still_refused(self, wired):
        """The exemption is for code-defined targets, not for every target."""
        from fastapi.testclient import TestClient

        db, agent_os = wired
        _draft_only(db, "catalog-only")
        client = TestClient(agent_os.get_app())
        r = client.post(
            "/schedules",
            json={"name": "nightly", "endpoint": "/agents/catalog-only/runs", "cron_expr": "0 0 * * *"},
        )
        assert r.status_code == 409, (r.status_code, r.text)

    def test_studio_enable_agrees_with_studio_create(self, tmp_path):
        """StudioTools' embedded scheduler must not refuse what Studio allowed."""
        from agno.registry import Registry
        from agno.tools.studio import StudioTools

        db = SqliteDb(id="wire-db-2", db_file=str(tmp_path / "wire2.db"))
        studio = StudioTools(
            registry=Registry(name="r", dbs=[db]),
            db=db,
            include_agents=[Agent(id="news-agent", name="News")],
            schedules=True,
        )
        assert studio._scheduler_tools is not None
        # The embedded scheduler sees the same set the run tools resolve from,
        # through live views (explicit lists, else the registry) - raw-list
        # identity would go stale the moment the registry fills in later.
        assert list(studio._scheduler_tools.include_agents) == list(studio.include_agents or [])
        _draft_only(db, "news-agent")
        probe = code_defined_probe(
            studio._scheduler_tools.include_agents,
            studio._scheduler_tools.include_teams,
            studio._scheduler_tools.include_workflows,
        )
        assert probe("agent", "news-agent") is True
