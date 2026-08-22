import json
import time

import pytest

from agno.agent.remote import RemoteAgent
from agno.os.routers.agents.schema import AgentResponse


def _remote_agent_with_tools(tools_value):
    remote_agent = RemoteAgent(base_url="http://example.invalid", agent_id="remote-agent")
    remote_agent._cached_agent_config = (
        AgentResponse(id="remote-agent", tools={"tools": tools_value}),
        time.time(),
    )
    return remote_agent


def test_remote_agent_tools_accepts_list_config():
    tools = [{"name": "search", "description": "Search things"}]
    remote_agent = _remote_agent_with_tools(tools)

    assert remote_agent.tools == tools


def test_remote_agent_tools_accepts_json_string_config():
    tools = [{"name": "search", "description": "Search things"}]
    remote_agent = _remote_agent_with_tools(json.dumps(tools))

    assert remote_agent.tools == tools


@pytest.mark.asyncio
async def test_remote_agent_aget_tools_accepts_list_config():
    tools = [{"name": "search", "description": "Search things"}]
    remote_agent = _remote_agent_with_tools(tools)

    assert await remote_agent.aget_tools() == tools
