"""Run content is the same in every run mode.

Each scenario runs with run, arun, run(stream=True) and arun(stream=True). The content the
caller gets, the content stored in the session and the stored assistant messages must equal
the expected value in all four modes.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any, Optional

import pytest
from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.exceptions import ModelProviderError
from agno.models.response import ModelResponse
from agno.run.agent import RunCompletedEvent, RunPausedEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.team.mode import TeamMode
from agno.team.team import Team
from agno.tools import tool
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow
from tests.unit.agent.test_run_content_last_model_call import MODE_IDS, MODES, ScriptedModel

NARRATION = "Let me check."
ANSWER = "Final."
NARRATED_SCRIPT = [{"content": NARRATION, "tool": "add_to_cart", "args": '{"item": "apples"}'}, {"content": ANSWER}]
MEMBER_SCRIPT = [
    {"content": "Member narration.", "tool": "add_to_cart", "args": '{"item": "apples"}'},
    {"content": "Member final."},
]
all_modes = pytest.mark.parametrize("stream,use_async", MODES, ids=MODE_IDS)


class RecordingModel(ScriptedModel):
    """A scripted model that records the messages of every model call."""

    def __init__(self, script: list, id: str = "scripted"):
        super().__init__(script)
        self.id = id
        self.name = id
        self.inputs: list = []

    def _record(self, kwargs: dict) -> None:
        messages = kwargs.get("messages") or []
        self.inputs.append([(m.role, m.get_content_string() if m.content else None) for m in messages])

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._record(kwargs)
        return super().invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        self._record(kwargs)
        yield from super().invoke_stream(*args, **kwargs)


class FailingModel(RecordingModel):
    """A model whose provider fails, after streaming some text when streaming."""

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise ModelProviderError("provider is down", status_code=500)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield ModelResponse(role="assistant", content="Partial text from the failed model.")
        raise ModelProviderError("provider is down", status_code=500)


def add_to_cart(item: str) -> str:
    """Add an item to the grocery cart."""
    return f"added {item}"


class Answer(BaseModel):
    name: str


@dataclass
class Observed:
    # What the caller gets: RunOutput.content, or the content of the last completed event when streaming
    content: Any
    # The content of the run stored in the session
    stored: Any
    # The texts of the stored run's assistant messages
    assistant: list


def plain(content: Any) -> Any:
    return content.model_dump() if isinstance(content, BaseModel) else content


def assistant_texts(run_output: Any) -> list:
    return [m.get_content_string() for m in run_output.messages or [] if m.role == "assistant" and m.content]


def collect(stream: Any, use_async: bool) -> list:
    if not use_async:
        return list(stream)

    async def drain() -> list:
        return [event async for event in stream]

    return asyncio.run(drain())


def observe(entity: Any, stream: bool, use_async: bool, **kwargs: Any) -> Observed:
    """Run an agent or team in one mode and read back its content from every place it is reported."""
    if stream:
        run = entity.arun if use_async else entity.run
        events = collect(run("q", stream=True, stream_events=True, **kwargs), use_async)
        terminal = [e for e in events if isinstance(e, (RunCompletedEvent, TeamRunCompletedEvent, RunPausedEvent))]
        content = terminal[-1].content
    elif use_async:
        content = asyncio.run(entity.arun("q", **kwargs)).content
    else:
        content = entity.run("q", **kwargs).content
    stored = entity.get_last_run_output()
    return Observed(content=plain(content), stored=plain(stored.content), assistant=assistant_texts(stored))


def assert_content(observed: Observed, content: Any, assistant: Optional[list] = None) -> None:
    assert observed.content == content
    assert observed.stored == content
    if assistant is not None:
        assert observed.assistant == assistant


def confirm_and_continue(agent: Agent, stream: bool, use_async: bool) -> Observed:
    """Confirm the tools of the agent's paused run and continue it in one mode."""
    run_output = agent.get_last_run_output()
    assert run_output.is_paused
    for tool_execution in run_output.tools_requiring_confirmation:
        tool_execution.confirmed = True

    continue_run = agent.acontinue_run if use_async else agent.continue_run
    if stream:
        events = collect(continue_run(run_response=run_output, stream=True, stream_events=True), use_async)
        content = [e for e in events if isinstance(e, RunCompletedEvent)][-1].content
    elif use_async:
        content = asyncio.run(continue_run(run_response=run_output)).content
    else:
        content = continue_run(run_response=run_output).content
    stored = agent.get_last_run_output()
    return Observed(content=plain(content), stored=plain(stored.content), assistant=assistant_texts(stored))


def make_agent(script: list, **kwargs: Any) -> Agent:
    kwargs.setdefault("tools", [add_to_cart])
    return Agent(model=RecordingModel(script), db=InMemoryDb(), **kwargs)


def make_team(leader_script: list, member_script: Optional[list] = None, **kwargs: Any) -> Team:
    member = Agent(
        name="shopper", model=RecordingModel(member_script or MEMBER_SCRIPT, id="member"), tools=[add_to_cart]
    )
    return Team(members=[member], model=RecordingModel(leader_script, id="leader"), db=InMemoryDb(), **kwargs)


def delegate(content: Optional[str] = None) -> dict:
    args = json.dumps({"member_id": "shopper", "task": "buy apples"})
    return {"content": content, "tool": "delegate_task_to_member", "args": args}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@all_modes
def test_narration_before_a_tool_call_is_not_content(stream: bool, use_async: bool):
    observed = observe(make_agent(NARRATED_SCRIPT), stream, use_async)
    assert_content(observed, ANSWER, assistant=[NARRATION, ANSWER])


@all_modes
def test_empty_final_call_keeps_the_last_written_text(stream: bool, use_async: bool):
    script = [
        {"content": "I added it for you.", "tool": "add_to_cart", "args": '{"item": "apples"}'},
        {"content": None},
    ]
    observed = observe(make_agent(script), stream, use_async)
    assert_content(observed, "I added it for you.", assistant=["I added it for you."])


@all_modes
@pytest.mark.parametrize("narration", [None, NARRATION], ids=["silent", "narrated"])
def test_show_result_output_stays_in_content_in_order(stream: bool, use_async: bool, narration: Optional[str]):
    @tool(show_result=True)
    def get_stories() -> str:
        """Get the top stories."""
        return "STORY-TABLE"

    script = [{"content": narration, "tool": "get_stories", "args": "{}"}, {"content": "Here are the top stories."}]
    observed = observe(make_agent(script, tools=[get_stories]), stream, use_async)
    assert_content(observed, "STORY-TABLEHere are the top stories.")


@all_modes
def test_stop_after_tool_call_shows_the_tool_output(stream: bool, use_async: bool):
    @tool(stop_after_tool_call=True)
    def lookup() -> str:
        """Look something up."""
        return "TOOL-OUT"

    script = [{"content": NARRATION, "tool": "lookup", "args": "{}"}]
    observed = observe(make_agent(script, tools=[lookup]), stream, use_async)
    assert_content(observed, NARRATION + "TOOL-OUT", assistant=[NARRATION])


@all_modes
@pytest.mark.parametrize(
    "continuation,expected",
    [("Done, it is deleted.", "Done, it is deleted."), (None, "I will delete it, please confirm.")],
    ids=["answered", "silent"],
)
def test_hitl_pause_and_continue(stream: bool, use_async: bool, continuation: Optional[str], expected: str):
    @tool(requires_confirmation=True)
    def delete_file(name: str) -> str:
        """Delete a file."""
        return f"deleted {name}"

    paused_text = "I will delete it, please confirm."
    script = [{"content": paused_text, "tool": "delete_file", "args": '{"name": "notes"}'}, {"content": continuation}]
    agent = make_agent(script, tools=[delete_file])

    paused = observe(agent, stream, use_async)
    assert_content(paused, paused_text, assistant=[paused_text])

    assert_content(confirm_and_continue(agent, stream, use_async), expected)
    stored = agent.get_last_run_output()
    assert [m.content for m in stored.messages if m.role == "tool"] == ["deleted notes"]


@all_modes
def test_show_result_tool_confirmed_by_the_user_stays_in_content(stream: bool, use_async: bool):
    @tool(requires_confirmation=True, show_result=True)
    def get_stories() -> str:
        """Get the top stories."""
        return "STORY-TABLE"

    script = [{"content": "Shall I fetch them?", "tool": "get_stories", "args": "{}"}, {"content": "Here they are."}]
    agent = make_agent(script, tools=[get_stories])
    observe(agent, stream, use_async)
    assert_content(confirm_and_continue(agent, stream, use_async), "STORY-TABLEHere they are.")


@all_modes
def test_output_schema_parses_the_final_text(stream: bool, use_async: bool):
    script = [{"content": NARRATION, "tool": "add_to_cart", "args": '{"item": "apples"}'}, {"content": '{"name": "x"}'}]
    observed = observe(make_agent(script, output_schema=Answer, use_json_mode=True), stream, use_async)
    assert_content(observed, {"name": "x"}, assistant=[NARRATION, '{"name": "x"}'])


@all_modes
def test_parser_model_reads_the_final_text(stream: bool, use_async: bool):
    script = [
        {"content": NARRATION, "tool": "add_to_cart", "args": '{"item": "apples"}'},
        {"content": "The name is x."},
    ]
    parser = RecordingModel([{"content": '{"name": "x"}'}], id="parser")
    observed = observe(make_agent(script, output_schema=Answer, parser_model=parser), stream, use_async)
    assert_content(observed, {"name": "x"})
    assert parser.inputs[-1][-1] == ("user", "The name is x.")


@all_modes
def test_output_model_writes_the_content(stream: bool, use_async: bool):
    output_model = RecordingModel([{"content": "Polished."}], id="output")
    observed = observe(make_agent(NARRATED_SCRIPT, output_model=output_model), stream, use_async)
    assert_content(observed, "Polished.")


@all_modes
def test_post_hook_sees_the_final_content(stream: bool, use_async: bool):
    seen = []

    def hook(run_output: Any) -> None:
        seen.append(run_output.content)

    observe(make_agent(NARRATED_SCRIPT, post_hooks=[hook]), stream, use_async)
    assert seen == [ANSWER]


@all_modes
@pytest.mark.parametrize(
    "script,expected",
    [
        (NARRATED_SCRIPT, ANSWER),
        (
            [
                {"content": "I added it for you.", "tool": "add_to_cart", "args": '{"item": "apples"}'},
                {"content": None},
            ],
            "I added it for you.",
        ),
    ],
    ids=["narration", "empty-final-call"],
)
def test_cache_hit_gives_the_same_content_as_a_miss(
    stream: bool, use_async: bool, script: list, expected: str, tmp_path
):
    observations = []
    models = []
    for _ in ("miss", "hit"):
        agent = make_agent(script)
        agent.model.cache_response = True
        agent.model.cache_dir = str(tmp_path)
        observations.append(observe(agent, stream, use_async))
        models.append(agent.model)

    miss, hit = observations
    assert [model.calls for model in models] == [2, 0]
    assert_content(miss, expected)
    assert_content(hit, expected)
    assert hit.assistant == miss.assistant


@all_modes
def test_fallback_model_answer_is_the_content(stream: bool, use_async: bool):
    fallback = RecordingModel(NARRATED_SCRIPT, id="fallback")
    agent = Agent(
        model=FailingModel([], id="primary"), fallback_models=[fallback], tools=[add_to_cart], db=InMemoryDb()
    )
    observed = observe(agent, stream, use_async)
    assert_content(observed, ANSWER, assistant=[NARRATION, ANSWER])


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------


@all_modes
def test_team_narration_before_a_tool_call_is_not_content(stream: bool, use_async: bool):
    team = Team(members=[], model=RecordingModel(NARRATED_SCRIPT), tools=[add_to_cart], db=InMemoryDb())
    observed = observe(team, stream, use_async)
    assert_content(observed, ANSWER, assistant=[NARRATION, ANSWER])


@all_modes
def test_delegation_hands_the_leader_the_member_final_content(stream: bool, use_async: bool):
    team = make_team([delegate("I'll ask the shopper."), {"content": "Team final."}])
    observed = observe(team, stream, use_async)
    assert_content(observed, "Team final.", assistant=["I'll ask the shopper.", "Team final."])
    # The leader reads the member's answer, not everything the member streamed
    assert [content for role, content in team.model.inputs[-1] if role == "tool"] == ["Member final."]


@all_modes
def test_respond_directly_returns_the_member_final_content(stream: bool, use_async: bool):
    team = make_team([delegate("Routing.")], respond_directly=True)
    observed = observe(team, stream, use_async)
    assert_content(observed, "Routing.Member final.", assistant=["Routing."])


@all_modes
def test_team_output_model_writes_the_content(stream: bool, use_async: bool):
    output_model = RecordingModel([{"content": "Polished."}], id="output")
    team = Team(
        members=[],
        model=RecordingModel(NARRATED_SCRIPT),
        tools=[add_to_cart],
        output_model=output_model,
        db=InMemoryDb(),
    )
    observed = observe(team, stream, use_async)
    assert_content(observed, "Polished.")


@all_modes
def test_tasks_mode_keeps_the_answer_written_with_mark_all_complete(stream: bool, use_async: bool):
    complete = {"content": "The answer is 42.", "tool": "mark_all_complete", "args": json.dumps({"summary": "done"})}
    team = make_team([complete, {"content": None}], mode=TeamMode.tasks)
    observed = observe(team, stream, use_async)
    assert_content(observed, "The answer is 42.", assistant=["The answer is 42."])


@all_modes
def test_tasks_mode_second_iteration_answer_is_the_content(stream: bool, use_async: bool):
    complete = {"content": "The answer is 42.", "tool": "mark_all_complete", "args": json.dumps({"summary": "done"})}
    team = make_team([{"content": "Planning."}, complete, {"content": None}], mode=TeamMode.tasks)
    observed = observe(team, stream, use_async)
    assert_content(observed, "The answer is 42.", assistant=["Planning.", "The answer is 42."])


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def run_workflow(workflow: Workflow, stream: bool, use_async: bool) -> Any:
    run = workflow.arun if use_async else workflow.run
    if stream:
        collect(run("q", stream=True, stream_events=True), use_async)
        return workflow.get_last_run_output()
    return asyncio.run(run("q")) if use_async else run("q")


def step_agent() -> Agent:
    return Agent(model=RecordingModel(NARRATED_SCRIPT), tools=[add_to_cart])


@all_modes
def test_workflow_agent_step_passes_on_the_final_content(stream: bool, use_async: bool):
    second_model = RecordingModel([{"content": "Step-2 final."}], id="second")
    workflow = Workflow(
        steps=[Step(name="first", agent=step_agent()), Step(name="second", agent=Agent(model=second_model))],
        db=InMemoryDb(),
    )
    output = run_workflow(workflow, stream, use_async)
    assert [step.content for step in output.step_results] == [ANSWER, "Step-2 final."]
    assert output.content == "Step-2 final."
    assert [content for role, content in second_model.inputs[-1] if role == "user"] == [ANSWER]


@all_modes
@pytest.mark.parametrize(
    "run_kwargs", [{"stream_events": True}, {"yield_run_output": True}], ids=["events", "run-output"]
)
def test_workflow_generator_step_matches_a_plain_step(stream: bool, use_async: bool, run_kwargs: dict):
    def plain_step(step_input: Any) -> StepOutput:
        return StepOutput(content=step_agent().run(step_input.input).content)

    def generator_step(step_input: Any) -> Iterator[Any]:
        yield from step_agent().run(step_input.input, stream=True, **run_kwargs)

    async def async_generator_step(step_input: Any) -> AsyncIterator[Any]:
        async for event in step_agent().arun(step_input.input, stream=True, **run_kwargs):
            yield event

    contents = []
    for executor in (plain_step, async_generator_step if use_async else generator_step):
        workflow = Workflow(steps=[Step(name="step", executor=executor)], db=InMemoryDb())
        output = run_workflow(workflow, stream, use_async)
        contents.append(([step.content for step in output.step_results], output.content))
    assert contents == [([ANSWER], ANSWER), ([ANSWER], ANSWER)]


@all_modes
def test_function_workflow_uses_the_run_final_content(stream: bool, use_async: bool):
    def steps(workflow: Workflow, execution_input: Any) -> Iterator[Any]:
        yield from step_agent().run(execution_input.input, stream=True, stream_events=True)

    async def async_steps(workflow: Workflow, execution_input: Any) -> AsyncIterator[Any]:
        async for event in step_agent().arun(execution_input.input, stream=True, stream_events=True):
            yield event

    workflow = Workflow(steps=async_steps if use_async else steps, db=InMemoryDb())
    assert run_workflow(workflow, stream, use_async).content == ANSWER
