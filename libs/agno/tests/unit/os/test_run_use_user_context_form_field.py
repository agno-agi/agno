"""The ``use_user_context`` run form field reaches the agent as a real boolean.

The field is declared on the route, so ``get_request_kwargs`` excludes it from
the pass-through kwargs; the route folds it back in explicitly. These tests pin
that plumbing end to end -- an incognito request must arrive at the run with
``use_user_context`` False, and an ordinary one with True -- because a silently
dropped flag would leave the caller believing a run was private when it was not.
"""

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS


class ScriptedModel(Model):
    """A model that answers without a provider call."""

    def __init__(self, model_id: str = "scripted-1", reply: str = "an answer"):
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


AGENT_RUNS = "/agents/incognito-agent/runs"


@pytest.fixture()
def agent_and_client(tmp_path):
    """An AgentOS whose agent records the flag as it lands on the RunContext.

    A pre-hook is the observation point rather than a wrapped ``arun``: the route
    resolves its own agent instance, so a subclass method would never be called,
    and the RunContext is what every downstream gate actually reads.
    """
    seen: List[Any] = []

    def record_flag(run_context) -> None:
        seen.append(run_context.use_user_context)

    db = SqliteDb(db_file=str(tmp_path / "use_user_context.db"))
    agent = Agent(
        id="incognito-agent",
        name="IncognitoAgent",
        model=ScriptedModel(),
        db=db,
        pre_hooks=[record_flag],
    )
    app = AgentOS(agents=[agent], db=db, telemetry=False).get_app()
    return seen, TestClient(app, raise_server_exceptions=False)


def _run(client: TestClient, *, use_user_context: Optional[str] = None):
    data: Dict[str, str] = {"message": "hi", "stream": "false"}
    if use_user_context is not None:
        data["use_user_context"] = use_user_context
    return client.post(AGENT_RUNS, data=data)


class TestFieldReachesTheRun:
    def test_absent_field_defaults_to_true(self, agent_and_client):
        seen, client = agent_and_client
        assert _run(client).status_code == 200
        assert seen == [True]

    @pytest.mark.parametrize("raw", ["false", "False", "0"])
    def test_falsey_values_arrive_as_false(self, agent_and_client, raw):
        seen, client = agent_and_client
        assert _run(client, use_user_context=raw).status_code == 200
        assert seen == [False]

    @pytest.mark.parametrize("raw", ["true", "True", "1"])
    def test_truthy_values_arrive_as_true(self, agent_and_client, raw):
        seen, client = agent_and_client
        assert _run(client, use_user_context=raw).status_code == 200
        assert seen == [True]

    def test_non_boolean_value_is_a_client_error(self, agent_and_client):
        """FastAPI types the field, so a junk value is a 422 rather than a silent True."""
        _, client = agent_and_client
        assert _run(client, use_user_context="banana").status_code == 422
