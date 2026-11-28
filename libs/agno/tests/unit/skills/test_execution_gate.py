"""Code-execution tools require confirmation once a run loads an MCP-served skill."""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

pytest.importorskip("mcp.server.extension")

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run import RunContext
from agno.run.requirement import RunRequirement
from agno.skills import Skills
from agno.skills.skill import Skill
from agno.team import Team
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

from .conftest import MockSkillLoader
from .loaders.test_mcp import SkillsServerState, make_loader

SHELL_CALLS: List[Any] = []


class ShellTools(Toolkit):
    """Named like agno's ShellTools, which the gate recognizes by class name."""

    def __init__(self) -> None:
        super().__init__(name="shell", tools=[self.run_shell_command, self.read_notes])

    def run_shell_command(self, args: List[str]) -> str:
        """Run a shell command.

        Args:
            args: The command and its arguments.
        """
        SHELL_CALLS.append(args)
        return "ran"

    def read_notes(self) -> str:
        """Read the notes."""
        return "notes"


class ScriptedModel(Model):
    """Replays scripted turns: ("tool", name, args, call_id) or ("content", text)."""

    def __init__(self, script: List[tuple]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        from agno.metrics import MessageMetrics

        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, call_id = turn
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            ]
        else:
            response = ModelResponse(content=turn[1], role="assistant")
            response.event = ModelResponseEvent.assistant_response.value
        response.response_usage = MessageMetrics(input_tokens=1, output_tokens=1, total_tokens=2)
        return response

    def invoke(self, *a, **k):
        return self._next()

    async def ainvoke(self, *a, **k):
        return self._next()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


LOAD = ("tool", "get_skill_instructions", {"skill_name": "docs/greeter"}, "c-load")


def _shell(n: int) -> tuple:
    return ("tool", "run_shell_command", {"args": ["echo", str(n)]}, f"c-shell-{n}")


def _confirmed(requirements) -> List[RunRequirement]:
    confirmed = []
    for data in [r.to_dict() for r in requirements or []]:
        requirement = RunRequirement.from_dict(data)
        requirement.confirm()
        confirmed.append(requirement)
    return confirmed


@pytest.fixture(autouse=True)
def _reset_shell_calls():
    SHELL_CALLS.clear()


def _agent(tmp_path, script: List[tuple], skills: Skills) -> Agent:
    return Agent(
        model=ScriptedModel(script),
        tools=[ShellTools()],
        skills=skills,
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        telemetry=False,
    )


# --- Agent runs ---


async def test_shell_call_pauses_after_an_mcp_skill_loads(tmp_path) -> None:
    agent = _agent(tmp_path, [LOAD, _shell(1), ("content", "done")], Skills(loaders=[make_loader(SkillsServerState())]))
    run = await agent.arun("go", session_id="s1")

    assert run.is_paused
    assert [r.tool_execution.tool_name for r in run.requirements] == ["run_shell_command"]
    assert SHELL_CALLS == []

    resumed = await agent.acontinue_run(run_id=run.run_id, session_id="s1", requirements=_confirmed(run.requirements))
    assert not resumed.is_paused
    assert SHELL_CALLS == [["echo", "1"]]


async def test_continued_run_stays_gated(tmp_path) -> None:
    script = [LOAD, _shell(1), _shell(2), ("content", "done")]
    agent = _agent(tmp_path, script, Skills(loaders=[make_loader(SkillsServerState())]))
    run = await agent.arun("go", session_id="s1")
    resumed = await agent.acontinue_run(run_id=run.run_id, session_id="s1", requirements=_confirmed(run.requirements))

    # The continued run rebuilds its tools; the earlier skill load still gates the next shell call.
    assert resumed.is_paused
    assert [r.tool_execution.tool_call_id for r in resumed.active_requirements] == ["c-shell-2"]
    assert SHELL_CALLS == [["echo", "1"]]


async def test_shell_call_runs_when_no_mcp_skill_was_loaded(tmp_path) -> None:
    agent = _agent(tmp_path, [_shell(1), ("content", "done")], Skills(loaders=[make_loader(SkillsServerState())]))
    run = await agent.arun("go", session_id="s1")
    assert not run.is_paused
    assert SHELL_CALLS == [["echo", "1"]]


async def test_loading_a_local_skill_does_not_gate(tmp_path) -> None:
    local = Skill(name="local-skill", description="Local", instructions="Body", source_path=str(tmp_path))
    skills = Skills(loaders=[MockSkillLoader([local]), make_loader(SkillsServerState())])
    script = [("tool", "get_skill_instructions", {"skill_name": "local-skill"}, "c-load"), _shell(1), ("content", "ok")]
    run = await _agent(tmp_path, script, skills).arun("go", session_id="s1")
    assert not run.is_paused
    assert SHELL_CALLS == [["echo", "1"]]


async def test_failed_mcp_skill_load_does_not_gate(tmp_path) -> None:
    state = SkillsServerState()
    state.files["skill://greeter/SKILL.md"] = "tampered"
    run = await _agent(tmp_path, [LOAD, _shell(1), ("content", "ok")], Skills(loaders=[make_loader(state)])).arun(
        "go", session_id="s1"
    )
    assert not run.is_paused
    assert SHELL_CALLS == [["echo", "1"]]


async def test_team_shell_call_pauses_after_an_mcp_skill_loads(tmp_path) -> None:
    member = Agent(name="member", model=ScriptedModel([("content", "hi")]), telemetry=False)
    team = Team(
        name="team",
        model=ScriptedModel([LOAD, _shell(1), ("content", "done")]),
        members=[member],
        tools=[ShellTools()],
        skills=Skills(loaders=[make_loader(SkillsServerState())]),
        db=SqliteDb(db_file=str(tmp_path / "team.db")),
        telemetry=False,
    )
    run = await team.arun("go", session_id="s1")
    assert run.is_paused
    assert SHELL_CALLS == []


async def test_gate_keeps_a_tool_s_existing_hitl_mode(tmp_path) -> None:
    from agno.tools import tool

    @tool(external_execution=True)
    def deploy(target: str) -> str:
        """Deploy to a target.

        Args:
            target: Where to deploy.
        """
        return "deployed"

    skills = Skills(loaders=[make_loader(SkillsServerState(), gate_all_tools=True)])
    script = [LOAD, ("tool", "deploy", {"target": "prod"}, "c-deploy"), ("content", "done")]
    agent = Agent(
        model=ScriptedModel(script),
        tools=[deploy],
        skills=skills,
        db=SqliteDb(db_file=str(tmp_path / "agent.db")),
        telemetry=False,
    )
    run = await agent.arun("go", session_id="s1")

    # One paused record for the call, in its own mode; confirmation is not stacked on top.
    assert run.is_paused
    records = [t for t in run.tools or [] if t.tool_call_id == "c-deploy"]
    assert len(records) == 1
    assert records[0].external_execution_required and not records[0].requires_confirmation


# --- Choosing the gated tools ---


def _run_functions(*toolkits: Toolkit) -> List[Function]:
    return [f for toolkit in toolkits for f in toolkit.get_functions().values()]


def _gated_names(skills: Skills, toolkits: List[Any], functions: List[Any]) -> List[str]:
    run_context = RunContext(run_id="r", session_id="s")
    skills.gate_execution_tools(toolkits, functions, run_context)
    return sorted(f.name for f in run_context.skill_gated_tools or [])


def _custom_tool() -> Function:
    def deploy() -> str:
        """Deploy."""
        return "deployed"

    return Function.from_callable(deploy)


def test_gate_picks_execution_functions_only() -> None:
    shell = ShellTools()
    assert _gated_names(Skills(loaders=[make_loader(SkillsServerState())]), [shell], _run_functions(shell)) == [
        "run_shell_command"
    ]


def test_gated_tools_adds_custom_tools() -> None:
    deploy = _custom_tool()
    skills = Skills(loaders=[make_loader(SkillsServerState(), gated_tools=["deploy"])])
    assert _gated_names(skills, [deploy], [deploy]) == ["deploy"]


def test_gate_all_tools_gates_everything_but_skill_tools() -> None:
    shell = ShellTools()
    skills = Skills(loaders=[make_loader(SkillsServerState(), gate_all_tools=True)])
    functions = _run_functions(shell) + skills.get_tools(async_mode=True)
    assert _gated_names(skills, [shell], functions) == ["read_notes", "run_shell_command"]


def test_no_gate_without_mcp_skills() -> None:
    shell = ShellTools()
    run_context = RunContext(run_id="r", session_id="s")
    Skills(loaders=[MockSkillLoader([])]).gate_execution_tools([shell], _run_functions(shell), run_context)
    assert run_context.skill_gated_tools is None
