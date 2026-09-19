"""Exercise explicit page tool registration through the actual Agent tool loop."""

import json
from types import SimpleNamespace

import pytest

from agno.agent import Agent
from agno.knowledge.page import PageChanged, PageError, PageFileSystem, PageList, tool_error
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse


class QueryModel(Model):
    def __init__(self, tool_name, description):
        super().__init__(id="page-tool-test", name="page-tool-test", provider="test")
        self.tool_name = tool_name
        self.description = description

    def invoke(self, messages, tools=None, **kwargs):
        assert len(tools) == 1
        function = tools[0]["function"]
        assert function["name"] == self.tool_name
        assert function["description"] == self.description
        assert function["parameters"]["properties"] == {"command": {"type": "string"}}
        assert function["parameters"]["required"] == ["command"]
        assert all(self.description not in str(message.content) for message in messages if message.role == "system")
        results = [message for message in messages if message.role == "tool"]
        if results:
            return ModelResponse(role="assistant", content=results[-1].content, response_usage=MessageMetrics())
        return ModelResponse(
            role="assistant",
            tool_calls=[
                {
                    "id": "read",
                    "type": "function",
                    "function": {
                        "name": self.tool_name,
                        "arguments": json.dumps({"command": "cat /a"}),
                    },
                }
            ],
            response_usage=MessageMetrics(),
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("custom", [False, True])
@pytest.mark.parametrize("error", [None, PageError(), PageChanged(current_revision="new")])
async def test_page_tool_agent_registration_execution_and_errors(monkeypatch, async_mode, custom, error):
    calls = []
    files = PageFileSystem(knowledge=SimpleNamespace())

    def execute(command):
        assert command == "cat /a"
        if error:
            raise error
        return "==> /a.md <==\nPublished page"

    def sync_command(command):
        calls.append("sync")
        return execute(command)

    async def async_command(command):
        calls.append("async")
        return execute(command)

    monkeypatch.setattr(files, "run_command", sync_command)
    monkeypatch.setattr(files, "arun_command", async_command)
    kwargs = {"tool_name": "query_docs_filesystem", "description": "Product-owned exact description."} if custom else {}
    toolkit = files.tools(**kwargs)
    name = kwargs.get("tool_name", "query_pages")
    assert list(toolkit.get_functions()) == list(toolkit.get_async_functions()) == [name]
    assert not toolkit.add_instructions and toolkit.instructions is None
    assert calls == []  # Construction does not set up storage or retrieve context.
    description = toolkit.functions[name].description
    if not custom:
        for example in ("cat", "rg", "ls", "30000", "Incomplete"):
            assert example in description
    agent = Agent(model=QueryModel(name, description), tools=[toolkit], telemetry=False)
    result = await agent.arun("Read the page") if async_mode else agent.run("Read the page")
    assert result.content == (tool_error(error) if error else "==> /a.md <==\nPublished page")
    assert calls == (["async"] if async_mode else ["sync"])
    # Direct callers retain typed failures, independent of the tool presentation.
    if error:
        with pytest.raises(type(error)):
            files.run_command("cat /a")


@pytest.mark.asyncio
async def test_page_tools_retain_command_bounds_and_readable_grammar_errors():
    knowledge = SimpleNamespace(
        list_pages=lambda **kwargs: PageList(pages=()),
    )
    files = PageFileSystem(knowledge=knowledge, max_output_chars=80)
    toolkit = files.tools()
    sync = toolkit.get_functions()["query_pages"].entrypoint
    async_ = toolkit.get_async_functions()["query_pages"].entrypoint
    assert sync("ls /") == await async_("ls /") == "The page index is empty."
    knowledge.list_pages = lambda **kwargs: SimpleNamespace(pages=[object()])
    command = "unsupported" * 1000
    assert sync(command) == files.run_command(command)
    assert await async_(command) == files.run_command(command)
    assert len(sync(command)) < 400
