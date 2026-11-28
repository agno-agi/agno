"""Extra form fields on the AgentOS run routes reach hooks and never break the run."""

from typing import Any, AsyncIterator, Dict, Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.team import Team


class OkModel(Model):
    """Offline model that always answers "ok"."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None

    def _reply(self) -> ModelResponse:
        return ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._reply()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._reply()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._reply()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._reply()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


@pytest.fixture
def os_client():
    seen: Dict[str, Any] = {}

    def guard(run_input: Any, tenant: Optional[str] = None) -> None:
        seen["tenant"] = tenant

    agent = Agent(id="a1", model=OkModel(), pre_hooks=[guard], telemetry=False)
    team = Team(id="t1", members=[], model=OkModel(), pre_hooks=[guard], telemetry=False)
    app = AgentOS(agents=[agent], teams=[team], telemetry=False).get_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, seen


ROUTES = ["/agents/a1/runs", "/teams/t1/runs"]

# Names the routes or the run pipeline bind themselves
COLLIDING_FIELDS = [
    "agent",
    "team",
    "input",
    "auth_token",
    "session",
    "run_input",
    "run_response",
    "run_messages",
    "hooks",
    "tools",
    "response_format",
]


@pytest.mark.parametrize("stream", ["false", "true"])
@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("field", COLLIDING_FIELDS)
def test_colliding_form_field_does_not_break_the_run(os_client, route, stream, field):
    client, _ = os_client

    response = client.post(route, data={"message": "hi", "stream": stream, field: "from-caller"})

    assert response.status_code == 200
    assert "RunError" not in response.text
    assert "multiple values" not in response.text


@pytest.mark.parametrize("route", ROUTES)
def test_custom_form_field_reaches_a_pre_hook(os_client, route):
    client, seen = os_client

    response = client.post(route, data={"message": "hi", "stream": "false", "tenant": "acme"})

    assert response.status_code == 200
    assert seen["tenant"] == "acme"
