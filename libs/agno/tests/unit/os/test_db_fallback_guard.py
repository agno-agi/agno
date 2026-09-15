"""A strict load never redirects persistence to the caller's db.

A stored component can declare a db the loader cannot reconstruct (the
connection field is never serialized, and the registry may not hold it).
Lenient loads fall back to the caller's db so the component stays readable
and repairable. A strict load - the dispatch path - must refuse instead:
running would durably write sessions and memory to a store other than the
one configured, and the caller cannot see that from the response.
"""

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.agent.agent import get_agent_by_id as get_agent_by_id_db
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.registry import Registry
from agno.team.team import Team
from agno.team.team import get_team_by_id as get_team_by_id_db
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from agno.workflow.workflow import get_workflow_by_id as get_workflow_by_id_db

FOREIGN_DB = {"type": "postgres", "id": "runtime-b", "session_table": "runtime_sessions"}


def _echo(step_input: StepInput) -> StepOutput:
    return StepOutput(content="ran")


@pytest.fixture
def catalog_db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "catalog.db"))


def _rewrite_stored_db(db, component_id, new_db_config):
    """Replace the declared db subtree in a component's stored config."""
    row = db.get_config(component_id=component_id)
    config = dict(row["config"])
    if new_db_config is None:
        config.pop("db", None)
    else:
        config["db"] = new_db_config
    db.upsert_config(component_id=component_id, config=config, stage="published")


@pytest.fixture
def redirected_components(catalog_db):
    """Agent, team and workflow whose stored configs declare an unreconstructable foreign db."""
    model = OpenAIChat(id="gpt-4o-mini")
    Agent(id="redirected-agent", name="RA", model=model).save(db=catalog_db)
    Team(id="redirected-team", name="RT", model=model, members=[]).save(db=catalog_db)
    Workflow(id="redirected-workflow", name="RW", steps=[Step(name="s", executor=_echo)]).save(db=catalog_db)
    for component_id in ("redirected-agent", "redirected-team", "redirected-workflow"):
        _rewrite_stored_db(catalog_db, component_id, FOREIGN_DB)
    return catalog_db


class TestStrictLoadRefusesDbRedirection:
    def test_agent_strict_load_refuses(self, redirected_components):
        with pytest.raises(ComponentRehydrationError, match="declares db 'runtime-b'"):
            Agent.load(id="redirected-agent", db=redirected_components, strict=True)

    def test_team_strict_load_refuses(self, redirected_components):
        with pytest.raises(ComponentRehydrationError, match="declares db 'runtime-b'"):
            get_team_by_id_db(db=redirected_components, id="redirected-team", strict=True)

    def test_workflow_strict_load_refuses(self, redirected_components):
        with pytest.raises(ComponentRehydrationError, match="declares db 'runtime-b'"):
            Workflow.load(
                id="redirected-workflow", db=redirected_components, registry=Registry(functions=[_echo]), strict=True
            )

    def test_module_loaders_refuse_instead_of_reporting_not_found(self, redirected_components):
        with pytest.raises(ComponentRehydrationError):
            get_agent_by_id_db(db=redirected_components, id="redirected-agent", strict=True)
        with pytest.raises(ComponentRehydrationError, match="declares db 'runtime-b'"):
            get_workflow_by_id_db(
                db=redirected_components, id="redirected-workflow", registry=Registry(functions=[_echo]), strict=True
            )


class TestLenientAndMatchingFallbacksSurvive:
    def test_lenient_load_still_falls_back(self, redirected_components):
        agent = Agent.load(id="redirected-agent", db=redirected_components, strict=False)
        assert agent is not None
        assert agent.db is redirected_components

    def test_matching_identity_still_falls_back_under_strict(self, catalog_db):
        """A declared db that IS the caller's db (mysql/mongo-style: identity
        serialized, connection not) keeps working under strict."""
        Agent(id="same-db-agent", name="SA", model=OpenAIChat(id="gpt-4o-mini")).save(db=catalog_db)
        _rewrite_stored_db(
            catalog_db, "same-db-agent", {"id": catalog_db.id, "session_table": catalog_db.session_table_name}
        )

        agent = Agent.load(id="same-db-agent", db=catalog_db, strict=True)
        assert agent is not None
        assert agent.db is catalog_db

    def test_no_declared_db_still_falls_back_under_strict(self, catalog_db):
        Agent(id="dbless-agent", name="DA", model=OpenAIChat(id="gpt-4o-mini")).save(db=catalog_db)
        _rewrite_stored_db(catalog_db, "dbless-agent", None)

        agent = Agent.load(id="dbless-agent", db=catalog_db, strict=True)
        assert agent is not None
        assert agent.db is catalog_db


class TestDispatchRefusalOverHttp:
    def test_dispatch_is_422_and_nothing_is_written_to_the_catalog_db(self, redirected_components):
        os = AgentOS(id="fallback-os", db=redirected_components, registry=Registry(functions=[_echo]))
        client = TestClient(os.get_app(), raise_server_exceptions=False)

        for path in (
            "/agents/redirected-agent/runs",
            "/teams/redirected-team/runs",
            "/workflows/redirected-workflow/runs",
        ):
            response = client.post(path, data={"message": "hi", "stream": "false"})
            assert response.status_code == 422, f"{path}: {response.status_code} {response.text[:200]}"
            assert "runtime-b" in response.text

        for session_type in (SessionType.AGENT, SessionType.TEAM, SessionType.WORKFLOW):
            sessions = redirected_components.get_sessions(session_type=session_type)
            assert sessions == [] or sessions == ([], 0)

    def test_reads_and_listings_stay_available(self, redirected_components):
        os = AgentOS(id="fallback-os-reads", db=redirected_components, registry=Registry(functions=[_echo]))
        client = TestClient(os.get_app(), raise_server_exceptions=False)

        listed = client.get("/agents")
        assert listed.status_code == 200
        assert any(item["id"] == "redirected-agent" for item in listed.json())
