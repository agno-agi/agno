from types import SimpleNamespace

import pytest

from agno.os import mcp as mcp_module


class _CapturingFastMCP:
    def __init__(self, *_args, **_kwargs):
        self.tools = {}

    def tool(self, name=None, **_kwargs):
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return decorator

    def http_app(self, *_args, **_kwargs):
        return None


class _StreamingByDefaultRunner:
    id = "runner"

    def __init__(self, output):
        self.output = output
        self.calls = []

    def arun(self, message, *, stream=None):
        self.calls.append((message, stream))
        if stream is False:
            return self._result()
        return self._stream()

    async def _result(self):
        return self.output

    async def _stream(self):
        yield self.output


def _capture_mcp_tools(monkeypatch):
    captured = {}

    class CapturingFastMCP(_CapturingFastMCP):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured["server"] = self

    monkeypatch.setattr(mcp_module, "FastMCP", CapturingFastMCP)
    mcp_module.get_mcp_server(
        SimpleNamespace(
            name="test-os",
            authorization=False,
            authorization_config=None,
            agents=[],
            teams=[],
            workflows=[],
        )
    )
    return captured["server"].tools


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "id_arg", "lookup_name"),
    [
        ("run_agent", "agent_id", "get_agent_by_id"),
        ("run_team", "team_id", "get_team_by_id"),
        ("run_workflow", "workflow_id", "get_workflow_by_id"),
    ],
)
async def test_mcp_run_tools_force_non_streaming(monkeypatch, tool_name, id_arg, lookup_name):
    runner = _StreamingByDefaultRunner(output={"content": "done"})
    monkeypatch.setattr(mcp_module, lookup_name, lambda *_args, **_kwargs: runner)

    tools = _capture_mcp_tools(monkeypatch)

    result = await tools[tool_name](**{id_arg: "runner", "message": "hello"})

    assert result == {"content": "done"}
    assert runner.calls == [("hello", False)]
