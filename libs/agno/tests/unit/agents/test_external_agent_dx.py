"""Public adapter construction, input validation, rendering and metadata contracts."""

import asyncio
import inspect
from dataclasses import dataclass, field, fields, replace
from typing import Any, Dict

import pytest

from agno.agents.antigravity import AntigravityAgent
from agno.agents.base import BaseExternalAgent, ExternalRunResult
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.agents.dspy import DSPyAgent
from agno.agents.langgraph import LangGraphAgent
from agno.db.sqlite import SqliteDb
from agno.exceptions import AgentRunException, RunCancelledException
from agno.models.response import ToolExecution
from agno.run.agent import RunContentEvent, RunOutput, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.run.base import RunStatus


@dataclass
class ExampleAgent(BaseExternalAgent):
    outcome: str = "completed"
    calls: list = field(default_factory=list)

    async def _arun_adapter(self, input: Any, **kwargs: Any):
        self.calls.append(kwargs)
        if self.outcome == "error":
            raise ValueError("provider unavailable")
        if self.outcome == "cancelled":
            raise RunCancelledException("cancelled")
        return ExternalRunResult(content="hello", warnings=[{"type": "test_warning"}])

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any):
        yield RunContentEvent(content="hello", run_id=kwargs["run_id"])
        yield ToolCallStartedEvent(tool=ToolExecution(tool_call_id="tool", tool_name="Read", tool_args={}))
        yield ToolCallCompletedEvent(tool=ToolExecution(tool_call_id="tool", tool_name="Read", result="file data"))
        await self._arun_adapter(input, **kwargs)


@pytest.mark.parametrize(
    "cls,sdk",
    [
        (BaseExternalAgent, "external"),
        (ClaudeAgent, "claude-agent-sdk"),
        (CodexAgent, "codex"),
        (LangGraphAgent, "langgraph"),
        (DSPyAgent, "dspy"),
        (AntigravityAgent, "antigravity"),
    ],
)
def test_builtin_constructors_are_keyword_only_and_sdk_is_metadata(cls, sdk):
    parameters = inspect.signature(cls).parameters
    assert all(param.kind == inspect.Parameter.KEYWORD_ONLY for param in parameters.values())
    assert "sdk" not in parameters and "framework" not in parameters
    with pytest.raises(TypeError):
        cls("positional name")
    with pytest.raises(TypeError):
        cls(framework="override")
    with pytest.raises(TypeError):
        cls(sdk="override")
    agent = cls(name="named")
    assert agent.sdk == agent.framework == sdk
    with pytest.raises(AttributeError):
        agent.sdk = "override"
    with pytest.raises(AttributeError):
        agent.framework = "override"
    assert "sdk" not in {item.name for item in fields(agent)}
    assert replace(agent, name="replacement").name == "replacement"


def test_claude_tool_parameters_are_adjacent_and_factories_remain_independent():
    names = list(inspect.signature(ClaudeAgent).parameters)
    assert names[names.index("tools") : names.index("tools") + 6] == [
        "tools",
        "allowed_tools",
        "disallowed_tools",
        "permission_mode",
        "mcp_servers",
        "strict_mcp_config",
    ]
    first = ClaudeAgent()
    second = ClaudeAgent()
    first.options_kwargs["model"] = "example"
    assert second.options_kwargs == {}


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("outcome", ["completed", "error", "cancelled"])
@pytest.mark.parametrize("raise_on_error", [False, True])
def test_printers_show_terminal_status_and_return_or_raise(
    stream, use_async, outcome, raise_on_error, capsys, tmp_path
):
    agent = ExampleAgent(id="printer", outcome=outcome, db=SqliteDb(db_file=str(tmp_path / "runs.db")))

    def invoke():
        kwargs = dict(stream=stream, raise_on_error=raise_on_error, session_id="session")
        if use_async:
            return asyncio.run(agent.aprint_response("question", **kwargs))
        return agent.print_response("question", **kwargs)

    if raise_on_error and outcome != "completed":
        expected = AgentRunException if outcome == "error" else RunCancelledException
        with pytest.raises(expected):
            invoke()
    else:
        result = invoke()
        assert isinstance(result, RunOutput)
        assert result.status == RunStatus(outcome.upper())
    output = capsys.readouterr().out
    assert "Status: " + outcome.upper() in output
    assert "None" not in output
    if outcome == "error":
        assert "Run failed" in output and "provider unavailable" in output
    elif outcome == "cancelled":
        assert "Run cancelled" in output
    elif stream:
        assert output.count("Read(") == 1
    else:
        assert "test_warning" in output
    assert len(agent.calls) == 1
    saved = agent.db.get_runs(session_id="session")
    assert len(saved) == 1 and saved[0].status == RunStatus(outcome.upper())


@pytest.mark.parametrize("use_async", [False, True])
def test_printers_reject_background_before_starting_work(use_async):
    agent = ExampleAgent()
    with pytest.raises(ValueError, match="background"):
        if use_async:
            asyncio.run(agent.aprint_response("question", background=True))
        else:
            agent.print_response("question", background=True)
    assert agent.calls == []


@pytest.mark.parametrize("kind", ["images", "audio", "videos", "files"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("use_async", [False, True])
def test_unsupported_media_fails_before_adapter_work(kind, stream, use_async, tmp_path):
    agent = ExampleAgent(db=SqliteDb(db_file=str(tmp_path / "runs.db")))
    with pytest.raises(ValueError, match=kind):
        # Validation happens at invocation, before a coroutine or generator starts work.
        (agent.arun if use_async else agent.run)("question", stream=stream, **{kind: [object()]})
    assert agent.calls == []
    assert agent.db.get_runs() == []


@pytest.mark.parametrize("use_async", [False, True])
def test_media_capable_adapter_receives_inputs(use_async):
    class MediaAgent(ExampleAgent):
        def _media_kwargs(self, **media: Any) -> Dict[str, Any]:
            return {name: values for name, values in media.items() if values}

    agent = MediaAgent()
    image = object()
    if use_async:
        result = asyncio.run(agent.arun("question", images=[image]))
    else:
        result = agent.run("question", images=[image])
    assert result.status == RunStatus.completed
    assert agent.calls[0]["images"] == [image]


def test_empty_media_is_accepted():
    agent = ExampleAgent()
    assert agent.run("question", images=[], files=[]).status == RunStatus.completed


def test_sdk_metadata_keeps_legacy_session_and_api_values(tmp_path):
    from fastapi.testclient import TestClient

    from agno.os import AgentOS
    from agno.os.schema import AgentSummaryResponse

    agent = ClaudeAgent(id="claude", db=SqliteDb(db_file=str(tmp_path / "runs.db")))
    expected = {"sdk": "claude-agent-sdk"}
    assert AgentSummaryResponse.from_agent(agent).metadata == expected
    session = agent._create_session("session", None)
    assert all(session.agent_data[key] == value for key, value in expected.items())
    assert "framework" not in session.agent_data, "only sdk is stored"
    # Sessions persisted before the rename carry framework instead of sdk and stay readable.
    session.agent_data = {"agent_id": "claude", "framework": "claude-agent-sdk"}
    agent.db.upsert_session(session)
    legacy = agent.read_or_create_session("session").agent_data
    assert (legacy.get("sdk") or legacy.get("framework")) == "claude-agent-sdk"
    with TestClient(AgentOS(agents=[agent]).get_app()) as client:
        listing = client.get("/agents")
        assert listing.status_code == 200
        assert listing.json()[0]["metadata"] == expected
        detail = client.get("/agents/claude")
        assert detail.status_code == 200
        assert detail.json()["metadata"] == expected


def test_legacy_custom_adapter_metadata():
    @dataclass
    class CustomAgent(ExampleAgent):
        framework: str = "custom-sdk"

    agent = CustomAgent()
    assert agent.sdk == agent.framework == "custom-sdk"
    assert agent._create_session("session", None).agent_data["sdk"] == "custom-sdk"


def test_public_typing_contract(tmp_path):
    pytest.importorskip("mypy")
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[5]
    fixture = Path(__file__).with_name("typing_external_agents.py")
    command = [
        sys.executable,
        "-m",
        "mypy",
        str(fixture),
        "--config-file",
        str(root / "libs/agno/pyproject.toml"),
    ]
    # A cold check follows the adapter and native SDK type graphs. CI can take longer
    # than 90 seconds; use a private cache to exercise that path and reuse it below.
    env = dict(os.environ, MYPYPATH=str(root / "libs/agno"), MYPY_CACHE_DIR=str(tmp_path / "mypy-cache"))
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    invalid = tmp_path / "positional.py"
    invalid.write_text('from agno.agents.claude import ClaudeAgent\nClaudeAgent("positional")\n')
    command[3] = str(invalid)
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode != 0
    assert "Too many positional arguments" in result.stdout
