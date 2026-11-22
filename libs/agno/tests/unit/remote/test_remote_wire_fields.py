"""Extra run fields a remote component sends to AgentOS arrive in the shape the run routes parse."""

from datetime import datetime
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agno.agent.remote import RemoteAgent
from agno.client import AgentOSClient
from agno.filters import EQ, GT
from agno.os.utils import get_request_kwargs
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.team.remote import RemoteTeam


class Answer(BaseModel):
    answer: str


@pytest.fixture
def parser_client() -> TestClient:
    """An endpoint that decodes form fields exactly as the AgentOS run routes do."""
    app = FastAPI()

    @app.post("/parse")
    async def parse(request: Request):
        kwargs = await get_request_kwargs(request, parse)
        filters = kwargs.get("knowledge_filters")
        schema = kwargs.get("output_schema")
        return {
            "keys": sorted(kwargs),
            "knowledge_filters": [f.to_dict() for f in filters] if isinstance(filters, list) else filters,
            "output_schema": schema.model_json_schema() if isinstance(schema, type) else schema,
            "dependencies": kwargs.get("dependencies"),
        }

    return TestClient(app)


async def _sent_form(**kwargs: Any) -> Dict[str, Any]:
    client = AgentOSClient(base_url="http://remote:7777")
    with patch.object(client, "_apost", new_callable=AsyncMock, return_value={"run_id": "r1"}) as post:
        await client.run_agent(agent_id="a1", message="hi", **kwargs)
    return post.call_args.args[1]


@pytest.mark.asyncio
async def test_filter_expressions_survive_the_round_trip(parser_client):
    form = await _sent_form(knowledge_filters=[EQ("region", "eu"), GT("year", 2020)])

    parsed = parser_client.post("/parse", data=form).json()

    assert parsed["knowledge_filters"] == [EQ("region", "eu").to_dict(), GT("year", 2020).to_dict()]


@pytest.mark.asyncio
async def test_output_schema_class_is_sent_as_its_json_schema(parser_client):
    form = await _sent_form(output_schema=Answer)

    parsed = parser_client.post("/parse", data=form).json()

    assert parsed["output_schema"]["properties"] == Answer.model_json_schema()["properties"]


@pytest.mark.asyncio
async def test_dict_fields_encode_values_json_cannot_hold(parser_client):
    form = await _sent_form(dependencies={"as_of": datetime(2026, 1, 2, 3, 4, 5)})

    parsed = parser_client.post("/parse", data=form).json()

    assert parsed["dependencies"] == {"as_of": "2026-01-02T03:04:05"}


@pytest.mark.asyncio
async def test_value_without_a_form_encoding_is_dropped_not_stringified():
    form = await _sent_form(handle=object(), note="kept")

    assert "handle" not in form
    assert form["note"] == "kept"


@pytest.mark.parametrize("name", ["run_context", "debug_mode", "yield_run_output", "background_tasks", "websocket"])
def test_run_routes_ignore_internal_run_options_sent_as_form_fields(parser_client, name):
    parsed = parser_client.post("/parse", data={name: "true", "note": "kept"}).json()

    assert parsed["keys"] == ["note"]


def _remote_agent() -> RemoteAgent:
    agent = RemoteAgent(base_url="http://remote:7777", agent_id="a1")
    agent.agentos_client.run_agent = AsyncMock(return_value=RunOutput(run_id="r1"))  # type: ignore[method-assign]
    return agent


def _remote_team() -> RemoteTeam:
    team = RemoteTeam(base_url="http://remote:7777", team_id="t1")
    team.agentos_client.run_team = AsyncMock(return_value=TeamRunOutput(run_id="r1"))  # type: ignore[method-assign]
    return team


@pytest.mark.asyncio
@pytest.mark.parametrize("make, method", [(_remote_agent, "run_agent"), (_remote_team, "run_team")])
async def test_remote_run_sends_run_context_fields_instead_of_the_context(make, method):
    remote = make()
    run_context = RunContext(
        run_id="r1",
        session_id="s1",
        dependencies={"tier": "gold"},
        metadata={"source": "workflow"},
        knowledge_filters={"region": "eu"},
    )

    await remote.arun("hi", stream=False, run_context=run_context, debug_mode=True, background_tasks=object())

    sent = getattr(remote.agentos_client, method).call_args.kwargs
    assert "run_context" not in sent
    assert "debug_mode" not in sent
    assert "background_tasks" not in sent
    assert sent["dependencies"] == {"tier": "gold"}
    assert sent["metadata"] == {"source": "workflow"}
    assert sent["knowledge_filters"] == {"region": "eu"}


@pytest.mark.asyncio
async def test_explicit_run_fields_win_over_the_run_context():
    remote = _remote_agent()
    run_context = RunContext(run_id="r1", session_id="s1", dependencies={"tier": "gold"}, metadata={"a": 1})

    await remote.arun("hi", stream=False, run_context=run_context, dependencies={"tier": "silver"})

    sent = remote.agentos_client.run_agent.call_args.kwargs
    assert sent["dependencies"] == {"tier": "silver"}
    assert sent["metadata"] == {"a": 1}


@pytest.mark.asyncio
async def test_remote_team_continue_does_not_send_background_tasks():
    team = RemoteTeam(base_url="http://remote:7777", team_id="t1")
    team.agentos_client.continue_team_run = AsyncMock(return_value=TeamRunOutput(run_id="r1"))  # type: ignore[method-assign]

    await team.acontinue_run(run_id="r1", requirements=[], stream=False, background_tasks=object())

    assert "background_tasks" not in team.agentos_client.continue_team_run.call_args.kwargs
