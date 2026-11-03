"""Harness agents (Claude Code here, through a fake SDK) as members of an Agno team.

The leader runs on a scripted model that delegates by tool call, so these exercise the
real team delegation path offline: the member's run lands in the team session, the
member keeps its own native conversation in a session derived from the team's, and the
team's session row is never overwritten by the member.
"""

import asyncio
import json
from types import ModuleType
from typing import Any, AsyncIterator, Dict, Iterator, List

import pytest

from agno.agents.claude import ClaudeAgent
from agno.agents.claude import agent as claude_module
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.base import RunStatus
from agno.team.team import Team
from tests.unit.agents.test_claude import (
    AssistantMessage,
    ClaudeAgentOptions,
    ProcessError,
    ResultError,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)


class _ScriptedModel(Model):
    """Replays ('tool', name, args, id) and ('content', text) turns offline."""

    def __init__(self, script: List[tuple]):
        super().__init__(id="leader-double", name="leader-double", provider="test")
        self._script = list(script)
        self._i = 0

    def __deepcopy__(self, memo: dict) -> "_ScriptedModel":
        return self

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
        response.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        return response

    def invoke(self, *a: Any, **k: Any):
        return self._next()

    async def ainvoke(self, *a: Any, **k: Any):
        return self._next()

    def invoke_stream(self, *a: Any, **k: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a: Any, **k: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **k: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


class _Sdk:
    """A fake claude_agent_sdk that answers per agent and remembers every prompt and resume."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.known: set = set()
        self.counter = 0


@pytest.fixture
def sdk(monkeypatch) -> _Sdk:
    state = _Sdk()
    module = ModuleType("claude_agent_sdk")

    async def query(prompt: str, options: ClaudeAgentOptions):
        state.calls.append({"prompt": prompt, "resume": options.resume})
        if options.resume is not None and options.resume not in state.known:
            raise ProcessError("Command failed with exit code 1")
        if options.resume is None:
            state.counter += 1
            session = f"sdk-{state.counter}"
            state.known.add(session)
        else:
            session = options.resume
        reply = f"answer from {session}"
        yield SystemMessage(subtype="init", data={"session_id": session})
        yield AssistantMessage(content=[TextBlock(text=reply)])
        yield ResultMessage(session_id=session, result=reply)

    class Client:
        def __init__(self, options):
            self.options = options

        async def connect(self):
            pass

        async def query(self, prompt):
            self.prompt = prompt

        def receive_response(self):
            return query(prompt=self.prompt, options=self.options)

        async def disconnect(self):
            pass

        async def interrupt(self):
            pass

    module.ClaudeSDKClient = Client  # type: ignore[attr-defined]
    for cls in (
        ClaudeAgentOptions,
        SystemMessage,
        TextBlock,
        AssistantMessage,
        ResultMessage,
        StreamEvent,
        UserMessage,
        ToolUseBlock,
        ToolResultBlock,
        ProcessError,
        ResultError,
    ):
        setattr(module, cls.__name__, cls)
    module.query = query  # type: ignore[attr-defined]
    monkeypatch.setattr(claude_module, "_sdk", lambda: module)
    return state


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "team.db"))


def _member(db, member_id: str = "claude-coder") -> ClaudeAgent:
    return ClaudeAgent(id=member_id, name=member_id.replace("-", " ").title(), description="Writes code", db=db)


def _team(db, members: List[ClaudeAgent], script: List[tuple]) -> Team:
    return Team(id="team", name="Team", members=members, model=_ScriptedModel(script), db=db)


def _delegate(member_id: str, task: str, call_id: str) -> tuple:
    return ("tool", "delegate_task_to_member", {"member_id": member_id, "task": task}, call_id)


def test_a_claude_member_takes_a_delegated_task_and_its_run_lands_in_the_team_session(db, sdk):
    member = _member(db)
    team = _team(db, [member], [_delegate("claude-coder", "Write hello.py", "c1"), ("content", "done")])

    output = team.run("Build a hello world", session_id="s1")

    assert output.status == RunStatus.completed and output.content == "done"
    [member_run] = output.member_responses
    assert member_run.agent_id == "claude-coder" and member_run.content == "answer from sdk-1"
    assert member_run.parent_run_id == output.run_id
    assert "Write hello.py" in sdk.calls[0]["prompt"]

    team_session = db.get_session(session_id="s1", session_type=SessionType.TEAM)
    assert team_session is not None, "the team's session row is the team's, not overwritten by the member"
    assert any(run.run_id == member_run.run_id for run in team_session.runs or [])

    state = db.get_session(session_id="s1:claude-coder", session_type=SessionType.AGENT)
    assert state is not None and (state.metadata or {}).get("team_id") == "team"
    assert state.session_data["claude_sdk_session_id"] == "sdk-1"
    assert not state.runs, "the member's runs are stored by the team, never twice"


def test_a_later_team_run_resumes_the_members_claude_session(db, sdk):
    member = _member(db)
    team = _team(
        db,
        [member],
        [
            _delegate("claude-coder", "Write hello.py", "c1"),
            ("content", "done"),
            _delegate("claude-coder", "Now test it", "c2"),
            ("content", "done"),
        ],
    )
    team.run("first", session_id="s1")
    team.run("second", session_id="s1")
    assert [call["resume"] for call in sdk.calls] == [None, "sdk-1"]


def test_two_claude_members_of_one_team_keep_separate_conversations(db, sdk):
    coder, reviewer = _member(db, "claude-coder"), _member(db, "claude-reviewer")
    team = _team(
        db,
        [coder, reviewer],
        [
            _delegate("claude-coder", "Write it", "c1"),
            _delegate("claude-reviewer", "Review it", "c2"),
            ("content", "done"),
        ],
    )
    output = team.run("Ship it", session_id="s1")
    assert {run.agent_id for run in output.member_responses} == {"claude-coder", "claude-reviewer"}
    coder_state = db.get_session(session_id="s1:claude-coder", session_type=SessionType.AGENT)
    reviewer_state = db.get_session(session_id="s1:claude-reviewer", session_type=SessionType.AGENT)
    assert coder_state.session_data["claude_sdk_session_id"] != reviewer_state.session_data["claude_sdk_session_id"]


def test_a_streamed_team_run_carries_the_members_events(db, sdk):
    member = _member(db)
    team = _team(db, [member], [_delegate("claude-coder", "Write hello.py", "c1"), ("content", "done")])

    async def consume():
        return [event async for event in team.arun("Build it", session_id="s1", stream=True, stream_events=True)]

    events = asyncio.run(consume())
    member_events = [event for event in events if getattr(event, "agent_id", None) == "claude-coder"]
    assert any(getattr(event, "content", None) == "answer from sdk-1" for event in member_events)
    assert getattr(events[-1], "event", None) == "TeamRunCompleted"


def test_a_sandboxed_member_forwards_only_sandbox_options_on_its_own_session(db, sdk):
    """A team hands every member native run options; a sandboxed member passes the sandbox only what it takes."""
    from agno.run.agent import RunContentEvent, RunOutput

    member = _member(db)
    team_options = dict(
        run_id="r1",
        session_id="s1",
        user_id="u1",
        metadata={"k": "v"},
        stream_events=True,
        yield_run_output=True,
        session_state={},
        dependencies={"x": 1},
        add_dependencies_to_context=False,
        add_session_state_to_context=False,
        knowledge_filters=None,
        debug_mode=False,
    )
    forwarded = member._sandboxed_member_kwargs(team_options, "s1", "r1", "team")
    assert forwarded == dict(
        run_id="r1.sandbox",
        session_id="s1:claude-coder",
        user_id="u1",
        metadata={"k": "v"},
        stream_events=True,
        yield_run_output=True,
        _session_metadata={"team_id": "team"},
    )
    run = member._as_team_member_output(
        RunOutput(run_id="r1.sandbox", session_id="s1:claude-coder", metadata={"sandbox": {"generation": 7}}),
        "s1",
        "r1",
        "r1.sandbox",
    )
    assert (run.run_id, run.session_id) == ("r1", "s1")
    assert run.metadata["sandbox"] == {"generation": 7, "run_id": "r1.sandbox"}
    event = member._as_team_member_output(
        RunContentEvent(run_id="r1.sandbox", session_id="s1:claude-coder", content="x"), "s1", "r1", "r1.sandbox"
    )
    assert (event.run_id, event.session_id) == ("r1", "s1")
    assert member._as_team_member_output("data: sse", "s1", "r1", "r1.sandbox") == "data: sse"


def test_role_stays_on_the_host_and_is_not_sent_to_the_sandbox_runtime():
    from agno.sandbox import _harness

    assert "role" in _harness._RUNTIME_OWNED


def test_message_input_from_a_team_becomes_text():
    assert ClaudeAgent._input_text(Message(role="user", content="hello")) == "hello"
    rendered = ClaudeAgent._input_text([Message(role="user", content="hi"), {"role": "assistant", "content": "yo"}])
    assert rendered == "user: hi\nassistant: yo"
    assert ClaudeAgent._input_text("plain") == "plain"
    blocks = [{"type": "text", "text": "hi"}]
    assert ClaudeAgent._input_text(blocks) is blocks, "a list that is not messages passes through unchanged"


def test_input_that_is_not_messages_never_leaves_the_session_claimed(db, sdk):
    member = _member(db)

    first = member.run([{"type": "text", "text": "hi"}], session_id="x")
    second = member.run("hello", session_id="x")

    assert first.status == RunStatus.completed and second.status == RunStatus.completed
    session = db.get_session(session_id="x", session_type=SessionType.AGENT)
    assert session is not None and len(session.runs) == 2


def test_a_message_input_is_stored_as_its_text_on_both_paths(db, sdk):
    member = _member(db)

    member.run(Message(role="user", content="hello"), session_id="m1")
    list(member.run(Message(role="user", content="hello"), session_id="m2", stream=True))

    for session_id in ("m1", "m2"):
        session = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        assert session is not None and session.runs[0].input.input_content == "hello"


def test_a_standalone_harness_agent_keeps_its_session_and_runs(db, sdk):
    member = _member(db)
    output = member.run("hello", session_id="solo")
    assert output.status == RunStatus.completed
    session = db.get_session(session_id="solo", session_type=SessionType.AGENT)
    assert session is not None and session.team_id is None and len(session.runs) == 1


def test_running_in_a_team_does_not_change_how_the_agent_saves_standalone_runs(db, sdk):
    member = _member(db)
    team = _team(db, [member], [_delegate("claude-coder", "Build", "c1"), ("content", "done")])
    team.run("Build", session_id="s1")

    output = member.run("hi", session_id="solo")
    streamed = list(member.run("again", session_id="solo-stream", stream=True, yield_run_output=True))

    assert output.status == RunStatus.completed
    session = db.get_session(session_id="solo", session_type=SessionType.AGENT)
    assert session is not None and session.team_id is None and [run.run_id for run in session.runs] == [output.run_id]
    assert db.get_session(session_id="solo:claude-coder", session_type=SessionType.AGENT) is None
    streamed_session = db.get_session(session_id="solo-stream", session_type=SessionType.AGENT)
    assert streamed_session is not None and [run.run_id for run in streamed_session.runs] == [streamed[-1].run_id]

    # The team's own state for the member is untouched by the standalone runs.
    state = db.get_session(session_id="s1:claude-coder", session_type=SessionType.AGENT)
    assert state is not None and (state.metadata or {}).get("team_id") == "team" and not state.runs


def test_one_harness_instance_serves_a_team_and_its_own_callers_at_once(db, sdk):
    # AgentOS hands out the same harness agent instance that a team holds as a member.
    member = _member(db)
    team = _team(db, [member], [_delegate("claude-coder", "Build", "c1"), ("content", "done")])

    async def both():
        return await asyncio.gather(team.arun("Build", session_id="s1"), member.arun("hi", session_id="solo"))

    team_output, solo_output = asyncio.run(both())

    assert team_output.status == RunStatus.completed and solo_output.status == RunStatus.completed
    [member_run] = team_output.member_responses
    team_session = db.get_session(session_id="s1", session_type=SessionType.TEAM)
    assert team_session is not None and any(run.run_id == member_run.run_id for run in team_session.runs or [])
    solo = db.get_session(session_id="solo", session_type=SessionType.AGENT)
    assert solo is not None and [run.run_id for run in solo.runs] == [solo_output.run_id]


def test_a_broadcast_team_streams_to_a_harness_member(db, sdk):
    from agno.team.mode import TeamMode

    member = _member(db)
    team = Team(
        id="team",
        name="Team",
        members=[member],
        mode=TeamMode.broadcast,
        model=_ScriptedModel([("tool", "delegate_task_to_members", {"task": "Review"}, "c1"), ("content", "done")]),
        db=db,
    )

    async def consume():
        return [event async for event in team.arun("Review it", session_id="s1", stream=True, stream_events=True)]

    events = asyncio.run(consume())

    assert getattr(events[-1], "event", None) == "TeamRunCompleted"
    assert any(
        getattr(event, "agent_id", None) == "claude-coder" and getattr(event, "content", None) == "answer from sdk-1"
        for event in events
    )
    assert db.get_session(session_id="s1:claude-coder", session_type=SessionType.AGENT) is not None


def test_a_codex_member_takes_a_delegated_task_and_resumes_its_thread(db, monkeypatch):
    from agno.agents.codex import CodexAgent
    from agno.agents.codex import agent as codex_module
    from tests.unit.agents import test_codex

    state = test_codex.FakeState()
    test_codex.FakeAsyncCodex.state = state
    module = ModuleType("openai_codex")
    for name in (
        "Sandbox",
        "ApprovalMode",
        "CodexConfig",
        "TextInput",
        "LocalImageInput",
        "ImageInput",
        "JsonRpcError",
    ):
        setattr(module, name, getattr(test_codex, name))
    module.AsyncCodex = test_codex.FakeAsyncCodex  # type: ignore[attr-defined]
    module.types = test_codex.SimpleNamespace(ReasoningEffort=test_codex.ReasoningEffort)  # type: ignore[attr-defined]
    monkeypatch.setattr(codex_module, "_sdk", lambda: module)
    monkeypatch.setattr(
        "agno.agents.codex._hitl.human_client",
        lambda config, bridge, **kwargs: test_codex.FakeAsyncCodex(config),
    )

    member = CodexAgent(id="codex-coder", name="Codex Coder", db=db)
    team = Team(
        id="team",
        name="Team",
        members=[member],
        model=_ScriptedModel(
            [
                _delegate("codex-coder", "Write it", "c1"),
                ("content", "done"),
                _delegate("codex-coder", "Fix it", "c2"),
                ("content", "done"),
            ]
        ),
        db=db,
    )
    first = team.run("first", session_id="s1")
    team.run("second", session_id="s1")
    [member_run] = first.member_responses
    assert member_run.agent_id == "codex-coder" and member_run.status == RunStatus.completed
    ops = [call["op"] for call in state.calls if call["op"] in ("thread_start", "thread_resume")]
    assert ops == ["thread_start", "thread_resume"], "the second team run continues the member's Codex thread"
    assert db.get_session(session_id="s1", session_type=SessionType.TEAM) is not None


def test_agentos_lists_a_harness_member_on_the_team(db, sdk):
    from agno.os.routers.teams.schema import TeamResponse

    member = ClaudeAgent(id="claude-coder", name="Claude Coder", description="Writes code", role="Engineer", db=db)
    team = _team(db, [member], [("content", "done")])
    response = asyncio.run(TeamResponse.from_team(team))
    [listed] = response.members
    assert (listed.id, listed.name, listed.role) == ("claude-coder", "Claude Coder", "Engineer")
    assert listed.metadata == {"sdk": "claude-agent-sdk"}


def test_a_harness_member_with_an_id_and_no_name_takes_delegated_tasks(db, sdk):
    from agno.utils.team import get_member_id

    member = ClaudeAgent(id="coder", db=db)
    team = _team(db, [member], [_delegate("coder", "Write hello.py", "c1"), ("content", "done")])

    output = team.run("Build", session_id="s1")

    assert get_member_id(member) == "coder"
    assert [(run.agent_id, run.status) for run in output.member_responses] == [("coder", RunStatus.completed)]


def test_a_harness_agent_does_not_pretend_to_have_native_member_settings(db, sdk):
    """Knowledge and storage flags are native agent settings; a harness agent never gains them, even after a run."""
    member = _member(db)
    team = Team(
        id="team",
        name="Team",
        members=[member],
        model=_ScriptedModel([_delegate("claude-coder", "Write it", "c1"), ("content", "done")]),
        db=db,
        send_media_to_model=False,
        enable_agentic_knowledge_filters=True,
    )
    assert team.run("go", session_id="s1").status == RunStatus.completed
    for name in (
        "knowledge",
        "knowledge_filters",
        "enable_agentic_knowledge_filters",
        "send_media_to_model",
        "store_media",
        "store_tool_messages",
        "store_history_messages",
    ):
        assert not hasattr(member, name), name


def test_member_setting_helpers_give_a_harness_member_the_defaults(db, sdk):
    from types import SimpleNamespace

    from agno.agent import Agent
    from agno.team._members import member_knowledge_filters, member_storage

    harness = _member(db)
    assert member_storage(harness).keeps_all
    opted_out = member_storage(Agent(id="native", store_media=False))
    assert not opted_out.media and opted_out.tool_messages and not opted_out.keeps_all

    run_context = SimpleNamespace(knowledge_filters={"topic": "billing"})
    assert member_knowledge_filters(harness, run_context) is None  # type: ignore[arg-type]
    with_knowledge = SimpleNamespace(knowledge=object(), knowledge_filters=None)
    assert member_knowledge_filters(with_knowledge, run_context) == {"topic": "billing"}  # type: ignore[arg-type]
    own_filters = SimpleNamespace(knowledge=object(), knowledge_filters={"topic": "own"})
    assert member_knowledge_filters(own_filters, run_context) is None  # type: ignore[arg-type]


def test_storage_paths_that_read_member_flags_keep_a_harness_members_run_whole(db, sdk):
    """Each path that applies a member's storage flags reaches a harness member without crashing and keeps its run."""
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput
    from agno.team._run import _scrub_member_responses, drop_opted_out_member_media
    from agno.team._session import _storage_view_of_spared_run

    member = _member(db)
    team = _team(db, [member], [("content", "done")])
    team.initialize_team()
    member_run = RunOutput(run_id="m1", agent_id="claude-coder", session_id="s1", content="answer")

    _scrub_member_responses(team, [member_run])
    assert member_run.content == "answer"
    drop_opted_out_member_media(team, TeamRunOutput(run_id="t1", team_id="team", member_responses=[member_run]))
    assert member_run.content == "answer"
    assert _storage_view_of_spared_run(team, member_run, member=member) is member_run


def test_a_team_that_stores_member_responses_runs_with_a_harness_member(db, sdk):
    member = _member(db)
    team = Team(
        id="team",
        name="Team",
        members=[member],
        model=_ScriptedModel([_delegate("claude-coder", "Write it", "c1"), ("content", "done")]),
        db=db,
        store_member_responses=True,
    )
    output = team.run("go", session_id="s1")
    assert output.status == RunStatus.completed
    stored = db.get_session(session_id="s1", session_type=SessionType.TEAM).runs
    team_run = next(run for run in stored if run.run_id == output.run_id)
    assert [run.agent_id for run in team_run.member_responses] == ["claude-coder"]
