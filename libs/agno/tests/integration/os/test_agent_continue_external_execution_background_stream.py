"""Integration test for the actual AgentOS HTTP surface: POST /agents/{id}/runs
then POST /agents/{id}/runs/{run_id}/continue with background=true&stream=true,
resolving an external_execution tool pause -- the exact request shape a real
client (agno-hooks or any other SDK) sends for HITL over SSE.

Regression coverage for the history-duplication bug fixed in
_build_continue_run_messages/session.get_messages (see the pure-Agent-API
matrix in tests/integration/agent/human_in_the_loop/
test_external_execution_background_stream.py for the underlying mechanism).
This test exists to prove the fix holds through the full router path too --
form-encoded body, the router's own tools -> requirements conversion, and the
background/event-stream plumbing -- not just via agent.arun/acontinue_run
called directly.
"""

import json

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.decorator import tool


@tool()
def get_weather() -> str:
    """Return the current weather. Runs immediately, no pause."""
    return "sunny, 25C"


@tool(external_execution=True)
def get_location() -> str:
    """Return the user's current location. Executed externally."""
    return ""


@pytest.fixture
def hitl_agent_client(temp_storage_db_file):
    db = SqliteDb(db_file=temp_storage_db_file)
    agent = Agent(
        id="hitl-external-exec-agent",
        name="HitlExternalExecAgent",
        instructions=[
            "Always call get_weather first, then call get_location. Call both tools before answering.",
        ],
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_weather, get_location],
        db=db,
        add_history_to_context=True,
        telemetry=False,
    )
    app = AgentOS(agents=[agent]).get_app()
    return TestClient(app), agent


def _parse_sse_events(response):
    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            data = line[6:]
            if data and data != "[DONE]":
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    pass
    return events


def test_continue_background_stream_over_http_resolves_external_execution(hitl_agent_client):
    client, agent = hitl_agent_client

    with client.stream(
        "POST",
        f"/agents/{agent.id}/runs",
        data={"message": "What's the weather and my location?", "background": "true", "stream": "true"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200
        create_events = _parse_sse_events(response)

    run_paused = next((e for e in create_events if e.get("event") == "RunPaused"), None)
    assert run_paused is not None, f"expected a RunPaused event, got events: {[e.get('event') for e in create_events]}"
    run_id = run_paused["run_id"]
    session_id = run_paused["session_id"]
    external_tool = next(t for t in run_paused["tools"] if t["external_execution_required"])
    assert external_tool["tool_name"] == "get_location"

    # Submit the ORIGINAL tool object back with only `result` filled in -- exactly
    # what a real client (agno-hooks' setExternalResult: `{ ...t, result }`) sends.
    # A submission that drops other fields (e.g. external_execution_required) makes
    # the router's from_dict reconstruction lose them, which independently breaks
    # message pairing -- a client-payload bug, not the history-duplication one this
    # test targets.
    resolved_tool = {**external_tool, "result": json.dumps({"lat": 1.0, "lng": 2.0})}
    tools_payload = json.dumps([resolved_tool])

    with client.stream(
        "POST",
        f"/agents/{agent.id}/runs/{run_id}/continue",
        data={"session_id": session_id, "background": "true", "stream": "true", "tools": tools_payload},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        assert response.status_code == 200
        continue_events = _parse_sse_events(response)

    error_events = [e for e in continue_events if e.get("event") == "RunError"]
    assert not error_events, (
        f"continue must not error -- this is exactly the history-duplication bug if it does: {error_events}"
    )

    completed = next((e for e in continue_events if e.get("event") == "RunCompleted"), None)
    assert completed is not None, f"expected RunCompleted, got events: {[e.get('event') for e in continue_events]}"
    content_lower = (completed.get("content") or "").lower()
    assert "25" in content_lower or "sunny" in content_lower, f"weather result missing: {completed.get('content')}"
    assert "1.0" in content_lower or "1" in content_lower, f"location result missing: {completed.get('content')}"
