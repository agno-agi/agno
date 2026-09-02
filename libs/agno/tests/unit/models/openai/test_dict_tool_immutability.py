"""Caller-supplied dict tools are configuration owned by the caller.

Formatting a request must never write into them: the same dict may be shared
across runs, agents, and providers, so every provider-specific rewrite
(adding "type", collapsing list-typed properties, stamping vector_store_ids)
has to happen on a copy.
"""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.media import File
from agno.models.message import Message
from agno.models.openai import OpenAIResponses


def _function_dict_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": ["string", "null"], "description": "City"}},
                "required": [],
            },
        },
    }


def _fake_response() -> SimpleNamespace:
    return SimpleNamespace(
        error=None,
        id="resp_1",
        status="completed",
        output=[SimpleNamespace(type="message", content=[])],
        output_text="hi",
        usage=None,
    )


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_closed.return_value = False
    client.responses.create.return_value = _fake_response()
    return client


def _mock_async_client() -> MagicMock:
    client = MagicMock()
    client.is_closed.return_value = False
    client.responses.create = AsyncMock(return_value=_fake_response())
    return client


class TestFormatToolParamsDoesNotMutate:
    def test_function_shaped_dict_is_not_mutated(self):
        model = OpenAIResponses(id="gpt-5.5", api_key="test-key")
        tool = _function_dict_tool()
        snapshot = json.dumps(tool)

        formatted = model._format_tool_params(messages=[], tools=[tool])

        assert json.dumps(tool) == snapshot
        # The request payload still gets the rewritten shape
        assert formatted[0]["type"] == "function"
        assert formatted[0]["name"] == "get_weather"
        assert formatted[0]["parameters"]["properties"]["city"]["type"] == "string"

    def test_file_search_dict_does_not_receive_vector_store_ids(self):
        model = OpenAIResponses(id="gpt-5.5", api_key="test-key")
        tool = {"type": "file_search"}
        snapshot = json.dumps(tool)
        messages = [Message(role="user", content="hi", files=[File(content=b"data", mime_type="text/plain")])]

        with (
            patch.object(model, "_upload_file", return_value="file_1"),
            patch.object(model, "_create_vector_store", return_value="vs_1"),
        ):
            formatted = model._format_tool_params(messages=messages, tools=[tool])

        assert formatted[0]["vector_store_ids"] == ["vs_1"]
        assert json.dumps(tool) == snapshot

    def test_base_format_tools_copies_dict_tools(self):
        model = OpenAIResponses(id="gpt-5.5", api_key="test-key")
        tool = _function_dict_tool()

        formatted = model._format_tools([tool])

        assert formatted[0] == tool
        assert formatted[0] is not tool
        # Nested containers must be copies too: downstream formatters rewrite them
        formatted[0]["function"]["parameters"]["properties"]["city"]["type"] = "string"
        assert tool["function"]["parameters"]["properties"]["city"]["type"] == ["string", "null"]


class TestAgentRunLeavesDictToolsIdentical:
    def test_sync_run(self):
        model = OpenAIResponses(id="gpt-5.5", api_key="test-key")
        model.client = _mock_client()

        fn_tool = _function_dict_tool()
        builtin_tool = {"type": "web_search"}
        fn_snapshot = copy.deepcopy(fn_tool)
        builtin_snapshot = copy.deepcopy(builtin_tool)

        agent = Agent(model=model, tools=[fn_tool, builtin_tool], telemetry=False)
        run = agent.run("hello")

        assert run.content == "hi"
        assert fn_tool == fn_snapshot
        assert builtin_tool == builtin_snapshot

    @pytest.mark.asyncio
    async def test_async_run(self):
        model = OpenAIResponses(id="gpt-5.5", api_key="test-key")
        model.async_client = _mock_async_client()

        fn_tool = _function_dict_tool()
        builtin_tool = {"type": "web_search"}
        fn_snapshot = copy.deepcopy(fn_tool)
        builtin_snapshot = copy.deepcopy(builtin_tool)

        agent = Agent(model=model, tools=[fn_tool, builtin_tool], telemetry=False)
        run = await agent.arun("hello")

        assert run.content == "hi"
        assert fn_tool == fn_snapshot
        assert builtin_tool == builtin_snapshot
