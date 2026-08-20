"""Zero-config Studio on AgentOS: the db resolves lazily, and a split
registry is loud.

StudioTools is constructed before AgentOS (it is a tool on an agent the OS
serves), and AgentOS fills registry.dbs only afterwards - by assigning its
db to the served components and collecting it from that tree, which is why
these tests serve the builder agent the way a real deployment does. A db snapshot taken
in __init__ therefore left StudioTools, its embedded StudioRunnerTools, and
its embedded SchedulerTools answering db_not_configured forever in exactly
the wiring the docs recommend. And when the user forgets registry= on
AgentOS, the OS populates a registry Studio never sees - previously with no
warning anywhere.
"""

import json
from importlib.util import find_spec

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.studio import StudioTools


def _model():
    return OpenAIResponses(id="gpt-5.5")


def _loads(raw: str):
    return json.loads(raw)


class TestLazyDbResolution:
    def test_studio_built_before_agentos_gets_the_os_db(self, tmp_path):
        # The exact wiring the cookbook recommends: toolkit first, OS second.
        registry = Registry(name="R", models=[_model()])
        studio = StudioTools(registry=registry)
        builder = Agent(id="builder", name="Builder", model=_model(), tools=[studio])
        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        AgentOS(agents=[builder], registry=registry, db=db)

        assert studio.db is db
        out = _loads(studio.create_agent(name="Made Later", instructions="i", publish=True))
        assert out.get("ok") is True, out

    def test_the_embedded_runner_resolves_too(self, tmp_path):
        registry = Registry(name="R", models=[_model()])
        studio = StudioTools(registry=registry)
        builder = Agent(id="builder", name="Builder", model=_model(), tools=[studio])
        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        AgentOS(agents=[builder], registry=registry, db=db)

        assert studio._runner_tools.db is db

    def test_an_explicit_db_still_wins(self, tmp_path):
        registry = Registry(name="R", models=[_model()])
        explicit = SqliteDb(id="explicit-db", db_file=str(tmp_path / "explicit.db"))
        studio = StudioTools(registry=registry, db=explicit)
        builder = Agent(id="builder", name="Builder", model=_model(), tools=[studio])
        os_db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        AgentOS(agents=[builder], registry=registry, db=os_db)

        assert studio.db is explicit
        assert studio._runner_tools.db is explicit

    def test_no_db_anywhere_still_answers_the_envelope(self):
        registry = Registry(name="R", models=[_model()])
        studio = StudioTools(registry=registry)

        out = _loads(studio.create_agent(name="Nowhere", instructions="i"))
        assert out.get("ok") is False
        assert out["error"]["code"] == "db_not_configured"


@pytest.mark.skipif(
    find_spec("croniter") is None or find_spec("pytz") is None,
    reason="scheduler extras not installed (pip install agno[scheduler])",
)
class TestLazySchedulerResolution:
    def test_the_embedded_scheduler_resolves_too(self, tmp_path):
        registry = Registry(name="R", models=[_model()])
        studio = StudioTools(registry=registry, schedules=True)
        builder = Agent(id="builder", name="Builder", model=_model(), tools=[studio])
        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        AgentOS(agents=[builder], registry=registry, db=db)

        assert studio._scheduler_tools is not None
        assert studio._scheduler_tools.manager.db is db
        assert _loads(studio.create_agent(name="target", instructions="i", publish=True))["ok"]
        out = _loads(
            studio.create_schedule(
                name="later-schedule",
                cron="0 9 * * *",
                target_type="agent",
                target_id="target",
                message="go",
            )
        )
        assert out.get("ok") is True, out

    def test_enable_schedule_allows_what_create_schedule_allowed(self, tmp_path):
        # The embedded SchedulerTools' code-defined probe must see the same
        # component set the run tools resolve from (registry included), or
        # enable_schedule refuses a target create_schedule just created.
        from agno.db.base import ComponentType

        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        db.create_component_with_config(
            component_id="news-agent",
            component_type=ComponentType.AGENT,
            name="news-agent",
            config={"name": "news-agent"},
            stage="draft",
        )
        registry = Registry(name="R", models=[_model()], dbs=[db])
        registry.agents.append(Agent(id="news-agent", name="News", model=_model()))
        studio = StudioTools(registry=registry, db=db, schedules=True)

        created = _loads(
            studio.create_schedule(
                name="news-schedule", cron="0 9 * * *", target_type="agent", target_id="news-agent", message="go"
            )
        )
        assert created.get("ok") is True, created
        schedule_id = created["data"]["id"]
        assert studio._scheduler_tools is not None
        disabled = _loads(studio._scheduler_tools.disable_schedule(schedule_id))
        assert "error" not in disabled, disabled

        enabled = _loads(studio._scheduler_tools.enable_schedule(schedule_id))

        assert "error" not in enabled, enabled

    def test_a_standalone_scheduler_keeps_its_eager_manager(self, tmp_path):
        from agno.tools.scheduler import SchedulerTools

        db = SqliteDb(id="sched-db", db_file=str(tmp_path / "sched.db"))
        scheduler = SchedulerTools(db=db)

        assert scheduler.manager.db is db


class TestFixesFromTheBranchReview:
    def test_a_callable_tools_factory_does_not_crash_construction(self, tmp_path):
        # Agent.tools may be a factory; the registry-split walk must skip it
        # rather than iterate it.
        def tools_factory(agent=None):
            return []

        agent = Agent(id="factory-agent", name="Factory", model=_model(), tools=tools_factory)
        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        AgentOS(agents=[agent], db=db)

    def test_the_os_db_outranks_an_agents_session_db_for_adoption(self, tmp_path):
        # The catalog routes are wired to the OS db; a Studio toolkit without
        # an explicit db must adopt THAT, not whichever agent-private db the
        # component walk happened to reach first.
        registry = Registry(name="R", models=[_model()])
        studio = StudioTools(registry=registry)
        session_db = SqliteDb(id="builder-sessions", db_file=str(tmp_path / "sessions.db"))
        builder = Agent(id="builder", name="Builder", model=_model(), db=session_db, tools=[studio])
        os_db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        AgentOS(agents=[builder], registry=registry, db=os_db)

        assert registry.dbs[0] is os_db
        assert studio.db is os_db

    def test_a_deep_copied_toolkit_resolves_through_its_own_copy(self):
        import copy

        registry = Registry(name="R", models=[_model()])
        studio = StudioTools(registry=registry, schedules=True)
        clone = copy.deepcopy(studio)

        assert clone._scheduler_tools is not None
        resolver_owner = getattr(clone._scheduler_tools._db_resolver, "__self__", None)
        assert resolver_owner is clone, "the copied scheduler must resolve through the copy, not the original"


class TestSplitRegistryIsLoud:
    def _studio_agent(self, registry, db=None):
        studio = StudioTools(registry=registry, db=db)
        return Agent(id="builder", name="Builder", model=_model(), tools=[studio])

    def test_forgetting_registry_on_agentos_warns(self, tmp_path, caplog):
        studio_registry = Registry(name="Studio R", models=[_model()])
        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        builder = self._studio_agent(studio_registry, db=db)

        with caplog.at_level("WARNING"):
            AgentOS(agents=[builder], db=db)

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_studio_toolkit_on_a_team_member_still_warns(self, tmp_path, caplog):
        from agno.team import Team

        studio_registry = Registry(name="Studio R", models=[_model()])
        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        member = self._studio_agent(studio_registry, db=db)
        team = Team(id="crew", name="Crew", members=[member], model=_model())

        with caplog.at_level("WARNING"):
            AgentOS(teams=[team], db=db)

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_studio_toolkit_on_a_workflow_step_agent_still_warns(self, tmp_path, caplog):
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        studio_registry = Registry(name="Studio R", models=[_model()])
        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        step_agent = self._studio_agent(studio_registry, db=db)
        workflow = Workflow(id="wf", name="WF", steps=[Step(name="s1", agent=step_agent)])

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[workflow], db=db)

        assert any("bound to a different Registry" in r.message for r in caplog.records)

    def test_a_shared_registry_stays_quiet(self, tmp_path, caplog):
        registry = Registry(name="Shared R", models=[_model()])
        db = SqliteDb(id="os-db", db_file=str(tmp_path / "os.db"))
        builder = self._studio_agent(registry, db=db)

        with caplog.at_level("WARNING"):
            AgentOS(agents=[builder], registry=registry, db=db)

        assert not any("bound to a different Registry" in r.message for r in caplog.records)
