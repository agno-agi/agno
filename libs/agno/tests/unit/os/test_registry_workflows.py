"""Workflows are registry citizens, symmetric with agents and teams.

The Registry tracks code-defined workflows; AgentOS mirrors its served
workflows in; Studio surfaces resolve them and dispatch them only behind the
same include_all_components gate agents and teams get; listings de-duplicate
registry-owned ids so a stored row sharing a code workflow's id is neither
double-listed in GET /workflows nor stranded in GET /components; nested
workflow steps rehydrate from the registry as isolated copies.
"""

import json
from importlib.util import find_spec
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import StudioRunnerTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


def _model():
    return OpenAIResponses(id="gpt-5.5")


def _wf(workflow_id: str, name: str) -> Workflow:
    agent = Agent(id=f"{workflow_id}-step-agent", name=f"{name} Agent", model=_model())
    return Workflow(id=workflow_id, name=name, steps=[Step(name="s1", agent=agent)])


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="registry-wf-db", db_file=str(tmp_path / "registry-wf.db"))


def _loads(raw: str):
    return json.loads(raw)


class TestRegistryBucket:
    def test_workflows_have_the_same_getters_as_agents_and_teams(self):
        wf = _wf("wf-1", "WF One")
        registry = Registry(name="R", workflows=[wf])

        assert registry.get_workflow("wf-1") is wf
        assert registry.get_workflow("ghost") is None
        assert registry.get_workflow_ids() == {"wf-1"}

    def test_get_all_component_ids_includes_workflows(self):
        registry = Registry(
            name="R",
            agents=[Agent(id="a-1", name="A", model=_model())],
            workflows=[_wf("wf-1", "WF One")],
        )
        assert registry.get_all_component_ids() == {"a-1", "wf-1", "wf-1-step-agent"} - {"wf-1-step-agent"}


class TestAgentOSSync:
    def test_served_workflows_are_mirrored_into_the_registry(self, db):
        wf = _wf("wf-os", "OS Workflow")
        os_app = AgentOS(workflows=[wf], db=db)

        assert [w.id for w in os_app.registry.workflows] == ["wf-os"]

    def test_repeated_population_does_not_duplicate(self, db):
        wf = _wf("wf-os", "OS Workflow")
        os_app = AgentOS(workflows=[wf], db=db)
        os_app._populate_registry()
        os_app._populate_registry()

        assert [w.id for w in os_app.registry.workflows] == ["wf-os"]

    def test_two_distinct_workflows_sharing_an_id_keep_the_first_and_warn(self, db, caplog):
        first = _wf("wf-dup", "First")
        second = _wf("wf-dup", "Second")
        registry = Registry(name="R", workflows=[first])

        with caplog.at_level("WARNING"):
            AgentOS(workflows=[second], db=db, registry=registry)

        assert registry.get_workflow("wf-dup") is first
        assert any("multiple distinct workflows share id" in r.message for r in caplog.records)

    def test_the_duplicate_id_warning_names_both_surfaces(self, db, caplog):
        """Nothing is discarded: the registry keeps one object and the OS keeps
        serving the other, so one id answers differently per surface."""
        first = _wf("wf-dup", "First")
        second = _wf("wf-dup", "Second")
        registry = Registry(name="R", workflows=[first])

        with caplog.at_level("WARNING"):
            agent_os = AgentOS(workflows=[second], db=db, registry=registry)

        # Both surfaces already disagree before the reword; the assertions are
        # the regression guard for what the message now claims.
        assert registry.get_workflow("wf-dup") is first
        assert agent_os.workflows is not None and agent_os.workflows[0] is second
        messages = [r.message for r in caplog.records if "multiple distinct workflows share id" in r.message]
        assert messages, [r.message for r in caplog.records]
        assert any("registry keeps the first" in message for message in messages)
        assert any("keeps serving the one it was constructed with" in message for message in messages)

    def test_a_workflow_without_an_id_is_skipped(self, db):
        # AgentOS mints ids for the workflows it is constructed with, so the
        # id-less case only reaches _populate_registry through later mutation.
        os_app = AgentOS(db=db)
        wf = _wf("wf-anon", "Anon")
        wf.id = None
        os_app.workflows = [wf]
        os_app._populate_registry()

        assert os_app.registry.workflows == []


class TestRunnerAdmission:
    def test_a_registry_workflow_stays_unlisted_until_it_is_admitted(self, db):
        # Mirror of the agents rule: a registry is passed so persisted
        # components can rehydrate, which is not consent to run -- or to
        # advertise -- every workflow the application happens to define.
        registry = Registry(name="R", models=[_model()], workflows=[_wf("internal-wf", "Internal")])

        unadmitted = _loads(StudioRunnerTools(registry=registry, db=db).list_workflows())
        assert all(entry["id"] != "internal-wf" for entry in unadmitted["workflows"])

        admitted = _loads(StudioRunnerTools(registry=registry, db=db, include_all_components=True).list_workflows())
        assert any(entry["id"] == "internal-wf" for entry in admitted["workflows"])

    def test_dispatch_needs_the_gate_but_reads_do_not(self, db):
        registry = Registry(name="R", models=[_model()], workflows=[_wf("internal-wf", "Internal")])
        runner = StudioRunnerTools(registry=registry, db=db)

        assert runner._iter_workflows(for_dispatch=True) == []
        assert [w.id for w in runner._iter_workflows(for_dispatch=False)] == ["internal-wf"]

    def test_an_explicit_include_list_wins_over_the_registry(self, db):
        registry = Registry(name="R", models=[_model()], workflows=[_wf("internal-wf", "Internal")])
        listed = _wf("listed-wf", "Listed")
        runner = StudioRunnerTools(registry=registry, db=db, include_workflows=[listed])

        dispatchable = [w.id for w in runner._iter_workflows(for_dispatch=True)]
        assert dispatchable == ["listed-wf"]

    def test_registry_instances_cover_workflows(self, db):
        wf = _wf("internal-wf", "Internal")
        registry = Registry(name="R", models=[_model()], workflows=[wf])
        runner = StudioRunnerTools(registry=registry, db=db, include_all_components=True)

        assert wf in runner._registry_instances()


class TestStudioToolsMirror:
    def test_include_workflows_are_mirrored_into_the_registry(self, db):
        registry = Registry(name="R", models=[_model()], dbs=[db])
        wf = _wf("wf-mirror", "Mirrored")
        StudioTools(registry=registry, db=db, include_workflows=[wf])

        assert registry.get_workflow("wf-mirror") is wf

    def test_distinct_objects_under_one_id_are_refused(self, db):
        registry = Registry(name="R", models=[_model()], dbs=[db], workflows=[_wf("wf-dup", "In Registry")])

        with pytest.raises(ValueError, match="include_workflows and the registry define distinct components"):
            StudioTools(registry=registry, db=db, include_workflows=[_wf("wf-dup", "In List")])


class TestListingDedup:
    def _os_with_code_and_stored(self, db):
        """A code workflow and a stored row share id 'wf-shared'; a second
        stored workflow 'wf-stored' exists only in the db.

        The stored rows are authored first, through a registry that does not
        hold the code workflow: with the code workflow already mirrored in,
        the id mint would (correctly) refuse the collision, but a row created
        before the code workflow existed is exactly the drift this dedup
        exists for."""
        seed_registry = Registry(name="Seed", models=[_model()], dbs=[db])
        studio = StudioTools(registry=seed_registry, db=db)
        assert _loads(studio.create_agent(name="step-agent", instructions="i", publish=True))["ok"]
        for wf_name in ("wf-shared", "wf-stored"):
            out = _loads(
                studio.create_workflow(
                    name=wf_name,
                    steps=[{"type": "step", "name": "s1", "agent_id": "step-agent"}],
                    publish=True,
                )
            )
            assert out.get("ok"), out
        code_wf = _wf("wf-shared", "Shared Workflow")
        return AgentOS(workflows=[code_wf], db=db)

    def test_get_workflows_lists_a_shared_id_once(self, db):
        os_app = self._os_with_code_and_stored(db)
        client = TestClient(os_app.get_app())

        ids = [w["id"] for w in client.get("/workflows").json()]
        assert ids.count("wf-shared") == 1
        assert ids.count("wf-stored") == 1

    def test_get_components_excludes_registry_owned_workflow_ids(self, db):
        # The other half of the same rule: GET /components serves stored rows
        # the registry does not own. Excluding 'wf-shared' here is only
        # correct because GET /workflows still lists it (above); the two must
        # move together.
        os_app = self._os_with_code_and_stored(db)
        client = TestClient(os_app.get_app())

        ids = [c["component_id"] for c in client.get("/components").json()["data"]]
        assert "wf-stored" in ids
        assert "wf-shared" not in ids


class TestRegistryRoute:
    def _client(self, registry):
        from agno.os.routers.registry import get_registry_router
        from agno.os.settings import AgnoAPISettings

        app = FastAPI()
        app.include_router(get_registry_router(registry=registry, settings=AgnoAPISettings()))
        return TestClient(app)

    def test_workflows_render_in_the_registry_listing(self):
        registry = Registry(name="R", workflows=[_wf("wf-listed", "Listed Workflow")])
        response = self._client(registry).get("/registry")

        assert response.status_code == 200
        entries = [r for r in response.json()["data"] if r["type"] == "workflow"]
        assert [e["id"] for e in entries] == ["wf-listed"]
        assert entries[0]["name"] == "Listed Workflow"

    def test_an_entry_with_neither_name_nor_id_does_not_500_the_route(self):
        # name is a required str on the response model; the class-name
        # fallback keeps one bad entry from taking down the whole listing.
        registry = Registry(name="R", workflows=[_wf("wf-ok", "Fine")])
        registry.workflows.append(SimpleNamespace(id=None, name=None, description=None))  # type: ignore[arg-type]
        registry.agents.append(SimpleNamespace(id=None, name=None, description=None))  # type: ignore[arg-type]
        registry.teams.append(SimpleNamespace(id=None, name=None, description=None))  # type: ignore[arg-type]

        response = self._client(registry).get("/registry")

        assert response.status_code == 200
        names = [r["name"] for r in response.json()["data"]]
        assert names.count("SimpleNamespace") == 3


class TestNestedWorkflowSteps:
    def test_a_registry_workflow_resolves_as_an_isolated_copy(self):
        wf = _wf("inner-wf", "Inner")
        registry = Registry(name="R", workflows=[wf])

        step = Step.from_dict({"name": "outer", "workflow_id": "inner-wf"}, registry=registry, strict=True)

        assert step.workflow is not None
        assert step.workflow.id == "inner-wf"
        assert step.workflow is not wf

    def test_an_unregistered_workflow_still_refuses_strictly(self):
        from agno.exceptions import ComponentRehydrationError

        registry = Registry(name="R", workflows=[_wf("inner-wf", "Inner")])

        with pytest.raises(ComponentRehydrationError, match="not found in the registry"):
            Step.from_dict({"name": "outer", "workflow_id": "ghost"}, registry=registry, strict=True)

    def test_an_unregistered_workflow_loads_leniently_as_a_placeholder(self):
        registry = Registry(name="R", workflows=[])

        step = Step.from_dict({"name": "outer", "workflow_id": "ghost"}, registry=registry, strict=False)

        assert getattr(step.executor, "__agno_unresolved__", None) == {"workflow_id": "ghost"}

    def test_a_deep_copy_that_returns_the_shared_instance_is_refused_strictly(self):
        from agno.exceptions import ComponentRehydrationError

        class SharedCopyWorkflow(Workflow):
            def deep_copy(self, *, update=None):
                return self

        agent = Agent(id="shared-agent", name="A", model=_model())
        wf = SharedCopyWorkflow(id="shared-wf", name="Shared", steps=[Step(name="s1", agent=agent)])
        registry = Registry(name="R", workflows=[wf])

        with pytest.raises(ComponentRehydrationError, match="deep_copy returned the shared"):
            Step.from_dict({"name": "outer", "workflow_id": "shared-wf"}, registry=registry, strict=True)

    def test_a_deep_copy_that_drops_the_steps_is_refused_strictly(self):
        from agno.exceptions import ComponentRehydrationError

        class EmptiedCopyWorkflow(Workflow):
            def deep_copy(self, *, update=None):
                return Workflow(id=self.id, name=self.name, steps=[])

        agent = Agent(id="emptied-agent", name="A", model=_model())
        wf = EmptiedCopyWorkflow(id="emptied-wf", name="Emptied", steps=[Step(name="s1", agent=agent)])
        registry = Registry(name="R", workflows=[wf])

        with pytest.raises(ComponentRehydrationError, match="deep_copy lost state"):
            Step.from_dict({"name": "outer", "workflow_id": "emptied-wf"}, registry=registry, strict=True)

        # A lenient load still admits the lossy copy.
        step = Step.from_dict({"name": "outer", "workflow_id": "emptied-wf"}, registry=registry, strict=False)
        assert step.workflow is not None
        assert step.workflow.steps == []

    def test_a_kwargs_swallowing_workflow_subclass_is_refused_strictly(self):
        from agno.exceptions import ComponentRehydrationError

        class SwallowingWorkflow(Workflow):
            def __init__(self, tenant="default", **kwargs):
                self.tenant = tenant
                super().__init__(**kwargs)

        agent = Agent(id="swallowed-agent", name="A", model=_model())
        wf = SwallowingWorkflow(tenant="t", id="swallowed-wf", name="Swallowed", steps=[Step(name="s1", agent=agent)])
        registry = Registry(name="R", workflows=[wf])

        with pytest.raises(ComponentRehydrationError, match="diverges from the original on: id, name, steps"):
            Step.from_dict({"name": "outer", "workflow_id": "swallowed-wf"}, registry=registry, strict=True)

    def test_a_step_whose_agent_reference_is_lost_is_refused_strictly(self):
        """A copy is refused when a step stops naming the executor the original named."""
        from agno.exceptions import ComponentRehydrationError

        class TopicAgent(Agent):
            def __init__(self, topic="general", **kwargs):
                self.topic = topic
                super().__init__(**kwargs)

        agent = TopicAgent(topic="x", id="topic-agent", name="A", model=_model(), instructions="follow the policy")
        wf = Workflow(id="lossy-child", name="Child", steps=[Step(name="s1", agent=agent)])
        registry = Registry(name="R", workflows=[wf])

        with pytest.raises(ComponentRehydrationError, match="deep_copy lost state"):
            Step.from_dict({"name": "outer", "workflow_id": "lossy-child"}, registry=registry, strict=True)

    def test_a_faithful_workflow_with_declared_steps_still_loads_strictly(self):
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel

        inner = Step(name="s1", agent=Agent(id="faithful-agent", name="A", model=_model()))
        wf = Workflow(
            id="faithful-wf",
            name="Faithful",
            steps=[Parallel(Loop(name="lp", steps=[inner], end_condition=lambda outputs, i: True), name="par")],
        )
        registry = Registry(name="R", workflows=[wf])

        step = Step.from_dict({"name": "outer", "workflow_id": "faithful-wf"}, registry=registry, strict=True)

        assert step.workflow is not None
        assert step.workflow is not wf

    def test_an_original_that_cannot_be_serialized_is_not_refused(self):
        """Nothing to measure against, so the copy is admitted rather than condemned."""

        class OpaqueWorkflow(Workflow):
            def to_dict(self):
                raise RuntimeError("not serializable")

        agent = Agent(id="opaque-agent", name="A", model=_model())
        wf = OpaqueWorkflow(id="opaque-wf", name="Opaque", steps=[Step(name="s1", agent=agent)])
        registry = Registry(name="R", workflows=[wf])

        step = Step.from_dict({"name": "outer", "workflow_id": "opaque-wf"}, registry=registry, strict=True)

        assert step.workflow is not None
        assert step.workflow is not wf

    def test_a_copy_that_cannot_be_serialized_is_refused_strictly(self):
        """A copy whose to_dict raises hides an arbitrary loss - here, every step."""
        from agno.exceptions import ComponentRehydrationError

        class UnserializableWorkflow(Workflow):
            def to_dict(self):
                raise RuntimeError("not serializable")

        class BrokenCopyWorkflow(Workflow):
            def deep_copy(self, *, update=None):
                return UnserializableWorkflow(id=self.id, name=self.name, steps=[])

        agent = Agent(id="broken-copy-agent", name="A", model=_model())
        wf = BrokenCopyWorkflow(id="broken-copy-wf", name="Broken", steps=[Step(name="s1", agent=agent)])
        registry = Registry(name="R", workflows=[wf])

        with pytest.raises(ComponentRehydrationError, match="could not be serialized"):
            Step.from_dict({"name": "outer", "workflow_id": "broken-copy-wf"}, registry=registry, strict=True)

        # A lenient load still admits the lossy copy, with no new warning to raise on.
        step = Step.from_dict({"name": "outer", "workflow_id": "broken-copy-wf"}, registry=registry, strict=False)
        assert step.workflow is not None
        assert step.workflow.steps == []

    def test_a_value_whose_equality_is_not_a_bool_does_not_refuse_the_copy(self):
        """An unmeasurable comparison means the copy is unmeasured, not diverged."""

        class Ambiguous:
            def __bool__(self):
                raise ValueError("the truth value of this value is ambiguous")

        class ArrayLike:
            def __eq__(self, other):
                return Ambiguous()

            __hash__ = None

        agent = Agent(id="ambiguous-agent", name="A", model=_model())
        wf = Workflow(
            id="ambiguous-wf",
            name="Ambiguous",
            description=ArrayLike(),
            steps=[Step(name="s1", agent=agent)],
        )
        registry = Registry(name="R", workflows=[wf])

        step = Step.from_dict({"name": "outer", "workflow_id": "ambiguous-wf"}, registry=registry, strict=True)

        assert step.workflow is not None
        assert step.workflow is not wf

    def test_an_unmeasurable_value_does_not_excuse_a_copy_that_dropped_its_steps(self):
        """One key that cannot be compared leaves every other key still judged."""
        from agno.exceptions import ComponentRehydrationError

        class Ambiguous:
            def __bool__(self):
                raise ValueError("the truth value of this value is ambiguous")

        class ArrayLike:
            def __eq__(self, other):
                return Ambiguous()

            __hash__ = None

        class AmbiguousAndLossyWorkflow(Workflow):
            def deep_copy(self, *, update=None):
                return Workflow(id=self.id, name=self.name, description=self.description, steps=[])

        agent = Agent(id="ambiguous-lossy-agent", name="A", model=_model())
        wf = AmbiguousAndLossyWorkflow(
            id="ambiguous-lossy-wf",
            name="AmbiguousAndLossy",
            description=ArrayLike(),
            steps=[Step(name="s1", agent=agent)],
        )
        registry = Registry(name="R", workflows=[wf])

        with pytest.raises(ComponentRehydrationError, match="diverges from the original on: steps"):
            Step.from_dict({"name": "outer", "workflow_id": "ambiguous-lossy-wf"}, registry=registry, strict=True)

    def test_a_nested_dependency_object_still_loads_strictly(self):
        """The runtime-state strip has to reach nested step configs, not just the top level."""

        class Plain:
            pass

        agent = Agent(
            id="nested-dep-agent",
            name="A",
            model=_model(),
            dependencies={"svc": Plain()},
        )
        wf = Workflow(id="nested-dep-wf", name="NestedDep", steps=[agent])
        registry = Registry(name="R", workflows=[wf])

        step = Step.from_dict({"name": "outer", "workflow_id": "nested-dep-wf"}, registry=registry, strict=True)

        assert step.workflow is not None
        assert step.workflow is not wf

    def test_runtime_state_holding_a_per_instance_object_still_loads_strictly(self):
        """session_state, dependencies and metadata are runtime state, not the work."""

        class Client:
            pass

        for index, key in enumerate(("session_state", "dependencies", "metadata")):
            agent = Agent(id=f"runtime-agent-{index}", name="A", model=_model())
            wf = Workflow(
                id=f"runtime-wf-{index}",
                name="Runtime",
                steps=[Step(name="s1", agent=agent)],
                **{key: {"client": Client()}},
            )
            registry = Registry(name="R", workflows=[wf])

            step = Step.from_dict(
                {"name": "outer", "workflow_id": f"runtime-wf-{index}"}, registry=registry, strict=True
            )

            assert step.workflow is not None
            assert step.workflow is not wf


@pytest.mark.skipif(find_spec("fastmcp") is None, reason="fastmcp not installed")
class TestMcpListingDedup:
    async def test_the_mcp_config_lists_a_shared_id_once(self, db):
        from fastmcp import Client

        from agno.os.mcp import build_mcp_server

        seed_registry = Registry(name="Seed", models=[_model()], dbs=[db])
        studio = StudioTools(registry=seed_registry, db=db)
        assert _loads(studio.create_agent(name="step-agent", instructions="i", publish=True))["ok"]
        out = _loads(
            studio.create_workflow(
                name="wf-shared", steps=[{"type": "step", "name": "s1", "agent_id": "step-agent"}], publish=True
            )
        )
        assert out.get("ok"), out
        os_app = AgentOS(workflows=[_wf("wf-shared", "Shared Workflow")], db=db, mcp_server=True)
        os_app.get_app()

        async with Client(build_mcp_server(os_app)) as client:
            result = await client.call_tool("get_agentos_config", {})

        structured = result.structured_content or {}
        payload = structured.get("result", structured)
        ids = [w["id"] for w in payload["workflows"]]
        assert ids.count("wf-shared") == 1


class TestMalformedStepConfigs:
    def test_a_workflow_id_beside_a_placeholder_executor_stays_loadable_leniently(self):
        registry = Registry(name="R", workflows=[_wf("inner-wf", "Inner")])

        step = Step.from_dict(
            {"name": "outer", "agent_id": "ghost-agent", "workflow_id": "inner-wf"}, registry=registry, strict=False
        )

        assert getattr(step.executor, "__agno_unresolved__", None) == {"agent_id": "ghost-agent"}

    def test_a_workflow_id_beside_an_executor_ref_is_a_typed_strict_refusal(self):
        from agno.exceptions import ComponentRehydrationError

        registry = Registry(name="R", workflows=[_wf("inner-wf", "Inner")])

        with pytest.raises(ComponentRehydrationError, match="alongside"):
            Step.from_dict(
                {"name": "outer", "executor_ref": "some_fn", "workflow_id": "inner-wf"},
                registry=registry,
                strict=True,
            )

    def test_a_deep_copy_of_the_wrong_type_is_refused_strictly(self):
        from agno.exceptions import ComponentRehydrationError

        class WrongTypeWorkflow(Workflow):
            def deep_copy(self, *, update=None):
                return object()

        agent = Agent(id="wrong-agent", name="A", model=_model())
        wf = WrongTypeWorkflow(id="wrong-wf", name="Wrong", steps=[Step(name="s1", agent=agent)])
        registry = Registry(name="R", workflows=[wf])

        with pytest.raises(ComponentRehydrationError, match="not a Workflow"):
            Step.from_dict({"name": "outer", "workflow_id": "wrong-wf"}, registry=registry, strict=True)


@pytest.mark.skipif(
    find_spec("croniter") is None or find_spec("pytz") is None,
    reason="scheduler extras not installed (pip install agno[scheduler])",
)
class TestSchedulerProbeSeesTheRegistry:
    def test_a_registry_workflow_with_a_draft_only_row_stays_schedulable(self, db):
        # A code-defined target is exempt from the draft-only refusal: its run
        # path resolves in process, so its catalog drafts never decide whether
        # the endpoint answers. The probe must see registry components the way
        # the run tools do, not just the include_* lists.
        from agno.db.base import ComponentType

        db.create_component_with_config(
            component_id="probe-wf",
            component_type=ComponentType.WORKFLOW,
            name="probe-wf",
            config={"name": "probe-wf"},
            stage="draft",
        )
        registry = Registry(name="R", models=[_model()], dbs=[db], workflows=[_wf("probe-wf", "Probe")])
        studio = StudioTools(registry=registry, db=db, schedules=True)

        out = _loads(
            studio.create_schedule(
                name="probe-schedule",
                cron="0 9 * * *",
                target_type="workflow",
                target_id="probe-wf",
                message="run it",
            )
        )

        assert out.get("ok") is True, out


class TestListingsExcludeWhatTheyRender:
    """An exclusion set must match the code half the listing actually renders.

    The registry is a superset of what an OS serves - it also carries
    rehydration context no listing shows - so subtracting the registry drops
    stored rows with nothing left to list them back. And the exclusion is
    keyed on id alone, so it has to be narrowed to the type being listed.
    """

    def _db(self, tmp_path):
        from agno.db.base import ComponentType

        db = SqliteDb(id="os-db", db_file=str(tmp_path / "c.db"))
        return db, ComponentType

    def test_a_code_workflow_does_not_hide_a_stored_agent_sharing_its_id(self, tmp_path):
        db, ComponentType = self._db(tmp_path)
        db.create_component_with_config(
            component_id="research",
            component_type=ComponentType.AGENT,
            name="Research",
            config={"id": "research", "name": "Research"},
            stage="published",
        )
        workflow = Workflow(id="research", name="Research WF", steps=[Step(name="s", executor=lambda si: None)])
        agent_os = AgentOS(agents=[Agent(id="a", name="A", model=_model())], workflows=[workflow], db=db)
        client = TestClient(agent_os.get_app())

        listed = client.get("/components", params={"component_type": "agent"}).json()["data"]

        assert [row["component_id"] for row in listed] == ["research"]

    def test_the_untyped_listing_still_hides_a_cross_type_collision(self, tmp_path):
        """Documents a known gap, so a fix changes a red test rather than a silent one.

        Without a type filter the exclusion is one flat set of ids, so it
        cannot tell same-type shadowing (intended: the code object is what
        /agents|/teams|/workflows renders, so the stored row is dead weight)
        from a cross-type collision (not intended: the typed listing above
        returns this row). The agent/team axis behaves this way already and
        always has; adding workflows to the registry extends it to a third
        type. Closing it needs type-aware exclusion pushed through
        list_components -- an adapter change -- and doing it by dropping
        workflow ids from this set instead would break the same-type dedup
        that TestListingDedup pins.
        """
        db, ComponentType = self._db(tmp_path)
        db.create_component_with_config(
            component_id="research",
            component_type=ComponentType.AGENT,
            name="Research",
            config={"id": "research", "name": "Research"},
            stage="published",
        )
        workflow = Workflow(id="research", name="Research WF", steps=[Step(name="s", executor=lambda si: None)])
        agent_os = AgentOS(agents=[Agent(id="a", name="A", model=_model())], workflows=[workflow], db=db)
        client = TestClient(agent_os.get_app())

        untyped = client.get("/components").json()

        assert [row["component_id"] for row in untyped["data"]] == []
        assert untyped["meta"]["total_count"] == 0

    def test_a_registry_only_workflow_does_not_hide_a_stored_workflow(self, tmp_path):
        db, ComponentType = self._db(tmp_path)
        db.create_component_with_config(
            component_id="shadow",
            component_type=ComponentType.WORKFLOW,
            name="Shadow",
            config={"id": "shadow", "name": "Shadow"},
            stage="published",
        )
        registry = Registry(name="R", models=[_model()])
        # In the registry for rehydration, but not served by this OS.
        registry.workflows.append(
            Workflow(id="shadow", name="Reg only", steps=[Step(name="s", executor=lambda si: None)])
        )
        agent_os = AgentOS(agents=[Agent(id="a", name="A", model=_model())], db=db, registry=registry)
        client = TestClient(agent_os.get_app())

        listed = client.get("/workflows").json()

        assert [w.get("id") for w in listed] == ["shadow"]

    def test_a_served_workflow_is_still_listed_once(self, tmp_path):
        db, ComponentType = self._db(tmp_path)
        db.create_component_with_config(
            component_id="served",
            component_type=ComponentType.WORKFLOW,
            name="Stored twin",
            config={"id": "served", "name": "Stored twin"},
            stage="published",
        )
        workflow = Workflow(id="served", name="Served", steps=[Step(name="s", executor=lambda si: None)])
        agent_os = AgentOS(workflows=[workflow], db=db)
        client = TestClient(agent_os.get_app())

        listed = client.get("/workflows").json()

        assert [w.get("id") for w in listed] == ["served"]


class TestOneExecutorPerStep:
    """The multi-executor guard has to see the executors that actually resolved."""

    def _config(self):
        return {"name": "nested", "agent_id": "a1", "workflow_id": "wf-x"}

    def _registry(self):
        registry = Registry(name="R", models=[_model()])
        registry.agents.append(Agent(id="a1", name="A1", model=_model()))
        registry.workflows.append(Workflow(id="wf-x", name="WFX", steps=[Step(name="s", executor=lambda si: None)]))
        return registry

    def test_a_resolvable_agent_alongside_a_workflow_loads_leniently(self):
        step = Step.from_dict(self._config(), registry=self._registry(), strict=False)

        # The non-workflow executor wins, and the step stays loadable rather
        # than failing Step's own one-executor check with a bare ValueError.
        assert step.agent is not None
        assert step.workflow is None

    def test_a_resolvable_agent_alongside_a_workflow_is_a_typed_strict_refusal(self):
        from agno.exceptions import ComponentRehydrationError

        with pytest.raises(ComponentRehydrationError, match="exactly one executor"):
            Step.from_dict(self._config(), registry=self._registry(), strict=True)

    def test_a_resolvable_team_alongside_a_workflow_is_refused_too(self):
        from agno.exceptions import ComponentRehydrationError
        from agno.team import Team

        registry = self._registry()
        registry.teams.append(Team(id="t1", name="T1", members=[], model=_model()))
        config = {"name": "nested", "team_id": "t1", "workflow_id": "wf-x"}

        with pytest.raises(ComponentRehydrationError, match="exactly one executor"):
            Step.from_dict(config, registry=registry, strict=True)

    def test_a_lone_workflow_id_still_resolves_from_the_registry(self):
        step = Step.from_dict({"name": "nested", "workflow_id": "wf-x"}, registry=self._registry(), strict=True)

        assert step.workflow is not None
        assert step.workflow.id == "wf-x"
