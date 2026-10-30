"""The ``store_run`` run form field: a temporary run answers normally but leaves no rows behind.

``store_run=false`` on the agent, team and workflow run routes returns the run output
without writing the run or its session to the database. The default (``true``) keeps
the existing behaviour. A temporary run cannot be a background run, because background
runs are polled from the stored run row, so that combination answers 400. An operator
can switch the option off for the whole OS with ``AgentOS(allow_temporary_runs=False)``,
which also answers 400 and is visible on ``GET /config``.
"""

from typing import Dict, Optional

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.registry import Registry
from agno.team.team import Team
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


class ScriptedModel(Model):
    """A model that answers without a provider call."""

    def __init__(self, model_id: str, reply: str):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._reply = reply

    def _resp(self) -> ModelResponse:
        return ModelResponse(content=self._reply, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs):
        return self._resp()

    async def ainvoke(self, *args, **kwargs):
        return self._resp()

    def invoke_stream(self, *args, **kwargs):
        yield self._resp()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._resp()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return self._resp()

    def _parse_provider_response_delta(self, response):
        return self._resp()


AGENT_RUNS = "/agents/tmp-agent/runs"
TEAM_RUNS = "/teams/tmp-team/runs"
WORKFLOW_RUNS = "/workflows/tmp-flow/runs"
SESSION_TYPES = {
    AGENT_RUNS: SessionType.AGENT,
    TEAM_RUNS: SessionType.TEAM,
    WORKFLOW_RUNS: SessionType.WORKFLOW,
}
ALL_RUN_ROUTES = list(SESSION_TYPES)


@pytest.fixture()
def db(tmp_path) -> SqliteDb:
    return SqliteDb(db_file=str(tmp_path / "store_run_form_field.db"))


@pytest.fixture()
def client(db: SqliteDb) -> TestClient:
    """An AgentOS whose agent, team and workflow are published catalog components."""
    model = ScriptedModel("scripted-1", "an answer")
    registry = Registry(name="store-run-registry", dbs=[db], models=[model])
    app = AgentOS(db=db, registry=registry, telemetry=False).get_app()

    agent = Agent(id="tmp-agent", name="TmpAgent", model=model)
    agent.save(db=db, stage="published")
    Team(id="tmp-team", name="TmpTeam", model=model, members=[agent]).save(db=db, stage="published")
    Workflow(id="tmp-flow", name="TmpFlow", steps=[Step(name="s1", agent=agent)]).save(db=db, stage="published")

    return TestClient(app, raise_server_exceptions=False)


def _run(
    client: TestClient,
    route: str,
    session_id: str,
    *,
    store_run: Optional[str] = None,
    stream: str = "false",
    background: Optional[str] = None,
):
    data: Dict[str, str] = {"message": "hi", "stream": stream, "session_id": session_id}
    if store_run is not None:
        data["store_run"] = store_run
    if background is not None:
        data["background"] = background
    return client.post(route, data=data)


def _stored_runs(db: SqliteDb, session_id: str) -> int:
    runs = db.get_runs(session_id=session_id)
    assert isinstance(runs, list)
    return len(runs)


class TestDefaultStillStores:
    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    def test_run_and_session_rows_are_written(self, client: TestClient, db: SqliteDb, route: str):
        response = _run(client, route, "kept")
        assert response.status_code == 200, response.text
        assert response.json()["content"] == "an answer"

        assert db.get_session(session_id="kept", session_type=SESSION_TYPES[route]) is not None
        assert _stored_runs(db, "kept") >= 1

    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    def test_explicit_true_matches_the_default(self, client: TestClient, db: SqliteDb, route: str):
        response = _run(client, route, "kept-explicit", store_run="true")
        assert response.status_code == 200, response.text
        assert db.get_session(session_id="kept-explicit", session_type=SESSION_TYPES[route]) is not None


class TestTemporaryRunLeavesNoRows:
    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    def test_response_is_returned_but_nothing_is_saved(self, client: TestClient, db: SqliteDb, route: str):
        response = _run(client, route, "temp", store_run="false")
        assert response.status_code == 200, response.text
        assert response.json()["content"] == "an answer"
        assert response.json()["session_id"] == "temp"

        assert db.get_session(session_id="temp", session_type=SESSION_TYPES[route]) is None
        assert _stored_runs(db, "temp") == 0

    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    def test_streaming_temporary_run_is_not_saved_either(self, client: TestClient, db: SqliteDb, route: str):
        response = _run(client, route, "temp-stream", store_run="false", stream="true")
        assert response.status_code == 200, response.text
        assert "an answer" in response.text

        assert db.get_session(session_id="temp-stream", session_type=SESSION_TYPES[route]) is None
        assert _stored_runs(db, "temp-stream") == 0

    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    def test_existing_session_is_left_untouched(self, client: TestClient, db: SqliteDb, route: str):
        assert _run(client, route, "shared").status_code == 200
        before = db.get_session(session_id="shared", session_type=SESSION_TYPES[route])
        assert before is not None
        runs_before = _stored_runs(db, "shared")

        response = _run(client, route, "shared", store_run="false")
        assert response.status_code == 200, response.text

        after = db.get_session(session_id="shared", session_type=SESSION_TYPES[route])
        assert after is not None
        assert _stored_runs(db, "shared") == runs_before
        assert after.to_dict(include_runs=False) == before.to_dict(include_runs=False)

        # The session keeps accepting stored runs afterwards.
        assert _run(client, route, "shared").status_code == 200
        assert _stored_runs(db, "shared") == runs_before * 2


class TestTemporaryRunCannotBeBackground:
    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    @pytest.mark.parametrize("stream", ["false", "true"])
    def test_answers_400(self, client: TestClient, db: SqliteDb, route: str, stream: str):
        response = _run(client, route, "bg", store_run="false", background="true", stream=stream)
        assert response.status_code == 400, response.text
        assert "store_run" in response.json()["detail"]
        assert db.get_session(session_id="bg", session_type=SESSION_TYPES[route]) is None


@pytest.fixture()
def strict_client(db: SqliteDb) -> TestClient:
    """An AgentOS whose operator disabled temporary runs."""
    model = ScriptedModel("scripted-1", "an answer")
    registry = Registry(name="strict-registry", dbs=[db], models=[model])
    app = AgentOS(db=db, registry=registry, telemetry=False, allow_temporary_runs=False).get_app()

    agent = Agent(id="tmp-agent", name="TmpAgent", model=model)
    agent.save(db=db, stage="published")
    Team(id="tmp-team", name="TmpTeam", model=model, members=[agent]).save(db=db, stage="published")
    Workflow(id="tmp-flow", name="TmpFlow", steps=[Step(name="s1", agent=agent)]).save(db=db, stage="published")

    return TestClient(app, raise_server_exceptions=False)


class TestOperatorCanDisableTemporaryRuns:
    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    def test_store_run_false_is_refused(self, strict_client: TestClient, db: SqliteDb, route: str):
        response = _run(strict_client, route, "refused", store_run="false")
        assert response.status_code == 400, response.text
        assert "disabled" in response.json()["detail"]
        assert db.get_session(session_id="refused", session_type=SESSION_TYPES[route]) is None

    @pytest.mark.parametrize("route", ALL_RUN_ROUTES)
    def test_stored_runs_are_unaffected(self, strict_client: TestClient, db: SqliteDb, route: str):
        for store_run in (None, "true"):
            response = _run(strict_client, route, "kept", store_run=store_run)
            assert response.status_code == 200, response.text
        assert db.get_session(session_id="kept", session_type=SESSION_TYPES[route]) is not None

    def test_config_reports_the_setting(self, client: TestClient, strict_client: TestClient):
        assert client.get("/config").json()["allow_temporary_runs"] is True
        assert strict_client.get("/config").json()["allow_temporary_runs"] is False
