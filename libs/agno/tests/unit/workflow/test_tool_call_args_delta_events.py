"""What a Workflow stores of a tool call's streamed argument fragments.

A workflow's steps run agents and teams, and their fragment events pass through
the workflow on the way to the caller. One fragment per handful of argument
characters means a single call can produce hundreds of them, so a workflow with
event storage on must not keep every one of them on the run it persists: the
default skip list holds them out of storage without holding them off the
stream. Everything a workflow stored before is stored still.
"""

import json
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunEvent
from agno.run.team import TeamRunEvent
from agno.run.workflow import WorkflowRunEvent, WorkflowRunOutput
from agno.team import Team
from agno.workflow import Step, Workflow

CHUNK_SIZE = 4
SESSION_ID = "notes-session"
WORKFLOW_ID = "notes"


class _ScriptedStreamModel(Model):
    """Replays a fixed script of provider deltas, one turn per model call.

    A call's id and function name ride its first fragment; every later fragment
    carries only an argument chunk and the index that ties it back to the call.

    The script is finite: a call past its end fails the test rather than
    replaying a turn, so a run that loops longer than intended is visible. The
    non-streaming paths answer out of the same script, so they cost a turn too
    and cannot quietly serve a run the script never provided for.
    """

    def __init__(self, turns: List[List[ModelResponse]]):
        super().__init__(id="scripted-stream", name="scripted-stream", provider="test")
        self._turns = list(turns)
        self._turn = 0

    def _next_turn(self) -> List[ModelResponse]:
        assert self._turn < len(self._turns), f"model called {self._turn + 1} times, script holds {len(self._turns)}"
        turn = self._turns[self._turn]
        self._turn += 1
        return turn

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield from self._next_turn()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        for delta in self._next_turn():
            yield delta

    def _aggregate_turn(self) -> ModelResponse:
        """The same turn as one finished response, for the non-streaming path."""
        turn = self._next_turn()
        aggregated = ModelResponse(role="assistant")
        fragments = [call for delta in turn for call in (delta.tool_calls or [])]
        if fragments:
            aggregated.tool_calls = self.parse_tool_calls(fragments)
        content = "".join(delta.content for delta in turn if isinstance(delta.content, str))
        if content:
            aggregated.content = content
        return aggregated

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._aggregate_turn()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._aggregate_turn()

    def _parse_provider_response(self, response, **kwargs) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_tool_calls(self, tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Reassemble the fragments by index, as OpenAI-compatible models do."""
        calls: Dict[int, Dict[str, Any]] = {}
        for fragment in tool_calls_data:
            index = fragment.get("index", 0)
            call = calls.setdefault(index, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
            if fragment.get("id"):
                call["id"] = fragment["id"]
            function = fragment.get("function") or {}
            if function.get("name"):
                call["function"]["name"] = function["name"]
            if function.get("arguments"):
                call["function"]["arguments"] += function["arguments"]
        return list(calls.values())


def save_note(note: str) -> str:
    """Save a note.

    Args:
        note: the note to save
    """
    return "saved"


def _fragment(
    index: int,
    arguments: str = "",
    tool_call_id: Optional[str] = None,
    tool_name: Optional[str] = None,
) -> ModelResponse:
    call: Dict[str, Any] = {"index": index, "type": "function", "function": {"arguments": arguments}}
    if tool_call_id is not None:
        call["id"] = tool_call_id
    if tool_name is not None:
        call["function"]["name"] = tool_name
    return ModelResponse(role="assistant", tool_calls=[call])


def _chunks(text: str, size: int) -> List[str]:
    return [text[start : start + size] for start in range(0, len(text), size)]


def _tool_call_turns() -> Tuple[List[List[ModelResponse]], str]:
    """A turn calling a tool in many fragments, then a turn replying."""
    arguments = json.dumps({"note": "a note long enough to arrive in many fragments"})
    fragments = [_fragment(0, arguments[:CHUNK_SIZE], tool_call_id="call_a", tool_name="save_note")]
    fragments += [_fragment(0, chunk) for chunk in _chunks(arguments[CHUNK_SIZE:], CHUNK_SIZE)]
    return [fragments, [ModelResponse(role="assistant", content="the note is saved")]], arguments


def _workflow(tmp_path, db_name: str, step: Step, **kwargs) -> Tuple[Workflow, str]:
    db_file = str(tmp_path / db_name)
    workflow = Workflow(
        id=WORKFLOW_ID,
        name="notes",
        steps=[step],
        db=SqliteDb(db_file=db_file),
        store_events=True,
        **kwargs,
    )
    return workflow, db_file


def _agent_step_workflow(tmp_path, db_name: str, **kwargs) -> Tuple[Workflow, str, str]:
    turns, arguments = _tool_call_turns()
    agent = Agent(name="writer", model=_ScriptedStreamModel(turns), tools=[save_note])
    workflow, db_file = _workflow(tmp_path, db_name, Step(name="write", agent=agent), **kwargs)
    return workflow, db_file, arguments


def _team_step_workflow(tmp_path, db_name: str, **kwargs) -> Tuple[Workflow, str, str]:
    turns, arguments = _tool_call_turns()
    team = Team(
        name="writers",
        members=[Agent(name="member", model=_ScriptedStreamModel([]))],
        model=_ScriptedStreamModel(turns),
        tools=[save_note],
    )
    workflow, db_file = _workflow(tmp_path, db_name, Step(name="write", team=team), **kwargs)
    return workflow, db_file, arguments


def _persisted_run(db_file: str) -> WorkflowRunOutput:
    """The run as the database holds it, read back through a fresh workflow.

    Asking the workflow that just ran answers out of its own in-memory session,
    which says nothing about what reached the db these tests configure.
    """
    fresh = Workflow(id=WORKFLOW_ID, db=SqliteDb(db_file=db_file))
    session = fresh.get_session(session_id=SESSION_ID)
    assert session is not None and session.runs, "the run was never persisted"
    return session.runs[-1]


def _fragments_of(events, event_name: str) -> str:
    return "".join(event.tool_args_delta for event in events if event.event == event_name)


def _stored(run_output: WorkflowRunOutput) -> List[str]:
    return [event.event for event in (run_output.events or [])]


def _assert_the_stream_kept_its_fragments(events, arguments: str, event_name: str) -> None:
    """The skip list governs storage, so a subscriber still sees every one."""
    assert _fragments_of(events, event_name) == arguments


def _assert_the_workflow_still_stores_what_it_stored(stored: List[str], step_events: List[str]) -> None:
    """Everything but the fragment event is stored as before."""
    for event_name in (
        WorkflowRunEvent.workflow_started.value,
        WorkflowRunEvent.step_started.value,
        WorkflowRunEvent.step_completed.value,
        WorkflowRunEvent.workflow_completed.value,
        *step_events,
    ):
        assert event_name in stored, f"{event_name} is no longer stored"


_AGENT_STEP_EVENTS = [
    RunEvent.run_started.value,
    RunEvent.tool_call_started.value,
    RunEvent.tool_call_completed.value,
    RunEvent.run_content.value,
    RunEvent.run_completed.value,
]

_TEAM_STEP_EVENTS = [
    TeamRunEvent.run_started.value,
    TeamRunEvent.tool_call_started.value,
    TeamRunEvent.tool_call_completed.value,
    TeamRunEvent.run_content.value,
    TeamRunEvent.run_completed.value,
]


def test_workflow_keeps_an_agent_steps_tool_call_arg_fragments_out_of_storage(tmp_path):
    workflow, db_file, arguments = _agent_step_workflow(tmp_path, "agent_step.db")

    events = list(workflow.run("go", session_id=SESSION_ID, stream=True, stream_events=True))
    stored = _stored(_persisted_run(db_file))

    _assert_the_stream_kept_its_fragments(events, arguments, RunEvent.tool_call_args_delta.value)
    assert RunEvent.tool_call_args_delta.value not in stored
    _assert_the_workflow_still_stores_what_it_stored(stored, _AGENT_STEP_EVENTS)


async def test_workflow_keeps_an_agent_steps_tool_call_arg_fragments_out_of_storage_async(tmp_path):
    workflow, db_file, arguments = _agent_step_workflow(tmp_path, "agent_step_async.db")

    events = [event async for event in workflow.arun("go", session_id=SESSION_ID, stream=True, stream_events=True)]
    stored = _stored(_persisted_run(db_file))

    _assert_the_stream_kept_its_fragments(events, arguments, RunEvent.tool_call_args_delta.value)
    assert RunEvent.tool_call_args_delta.value not in stored
    _assert_the_workflow_still_stores_what_it_stored(stored, _AGENT_STEP_EVENTS)


def test_workflow_keeps_a_team_steps_tool_call_arg_fragments_out_of_storage(tmp_path):
    """A team step carries the team's own fragment event, which is its own name."""
    workflow, db_file, arguments = _team_step_workflow(tmp_path, "team_step.db")

    events = list(workflow.run("go", session_id=SESSION_ID, stream=True, stream_events=True))
    stored = _stored(_persisted_run(db_file))

    _assert_the_stream_kept_its_fragments(events, arguments, TeamRunEvent.tool_call_args_delta.value)
    assert TeamRunEvent.tool_call_args_delta.value not in stored
    _assert_the_workflow_still_stores_what_it_stored(stored, _TEAM_STEP_EVENTS)


async def test_workflow_keeps_a_team_steps_tool_call_arg_fragments_out_of_storage_async(tmp_path):
    workflow, db_file, arguments = _team_step_workflow(tmp_path, "team_step_async.db")

    events = [event async for event in workflow.arun("go", session_id=SESSION_ID, stream=True, stream_events=True)]
    stored = _stored(_persisted_run(db_file))

    _assert_the_stream_kept_its_fragments(events, arguments, TeamRunEvent.tool_call_args_delta.value)
    assert TeamRunEvent.tool_call_args_delta.value not in stored
    _assert_the_workflow_still_stores_what_it_stored(stored, _TEAM_STEP_EVENTS)


def _opted_in_skip_list(skips_but_the_argument_fragments) -> List[Any]:
    """The workflow default with the fragment events taken out of it.

    Which is a request for the fragments and for nothing else that was already
    stored, whatever else that default comes to hold.
    """
    return skips_but_the_argument_fragments(Workflow(id=WORKFLOW_ID, steps=[]))


def test_workflow_stores_tool_call_arg_fragments_when_the_caller_asks_for_them(
    tmp_path, skips_but_the_argument_fragments
):
    workflow, db_file, arguments = _agent_step_workflow(
        tmp_path, "opted_in.db", events_to_skip=_opted_in_skip_list(skips_but_the_argument_fragments)
    )

    list(workflow.run("go", session_id=SESSION_ID, stream=True, stream_events=True))

    assert _fragments_of(_persisted_run(db_file).events or [], RunEvent.tool_call_args_delta.value) == arguments


async def test_workflow_stores_tool_call_arg_fragments_when_the_caller_asks_for_them_async(
    tmp_path, skips_but_the_argument_fragments
):
    workflow, db_file, arguments = _agent_step_workflow(
        tmp_path, "opted_in_async.db", events_to_skip=_opted_in_skip_list(skips_but_the_argument_fragments)
    )

    [event async for event in workflow.arun("go", session_id=SESSION_ID, stream=True, stream_events=True)]

    assert _fragments_of(_persisted_run(db_file).events or [], RunEvent.tool_call_args_delta.value) == arguments
