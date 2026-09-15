"""Shared offline model, response builders and run drivers for the verifiers suite."""

import json
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Tuple, Union

import pytest

from agno.agent import Agent
from agno.media import Image
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput
from agno.team import Team
from agno.tools import tool
from agno.verifiers.report import is_verification_report


class ScriptedModel(Model):
    """Returns one scripted ModelResponse per provider call, in order, recording the messages
    every call received. `mutations[i]` runs before call i is answered."""

    def __init__(
        self, script: List[ModelResponse], mutations: Optional[List[Optional[Callable[[], None]]]] = None
    ) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.mutations = list(mutations or [])
        self.calls = 0
        self.seen: List[List[str]] = []

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self  # one shared call counter, whatever the agent copies

    def _next(self, kwargs: Optional[Dict[str, Any]] = None) -> ModelResponse:
        self.seen.append([str(m.content) for m in (kwargs or {}).get("messages", [])])
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        if index < len(self.mutations) and self.mutations[index] is not None:
            self.mutations[index]()
        return self.script[index]

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next(kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next(kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next(kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next(kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _text(content: str) -> ModelResponse:
    response = ModelResponse(role="assistant", content=content)
    response.event = ModelResponseEvent.assistant_response.value
    response.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
    return response


def _tool_call(name: str, call_id: str, arguments: Optional[Dict[str, Any]] = None) -> ModelResponse:
    response = ModelResponse(
        role="assistant",
        tool_calls=[
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments or {})}}
        ],
    )
    response.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
    return response


def _image_response(content: str, url: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content, images=[Image(url=url)])


def _image_urls(out: RunOutput) -> List[str]:
    return [image.url for image in (out.images or [])]


MODES = pytest.mark.parametrize("mode", ["run", "arun", "run_stream", "arun_stream"])


async def _run_variant(
    owner: Union[Agent, Team], mode: str, prompt: str = "go", **kwargs: Any
) -> Union[RunOutput, TeamRunOutput]:
    """Drive an agent or team through one of the four run variants to its final output."""
    output_type = TeamRunOutput if isinstance(owner, Team) else RunOutput
    if mode == "run":
        return owner.run(prompt, **kwargs)
    if mode == "arun":
        return await owner.arun(prompt, **kwargs)
    stream_kwargs = dict(stream=True, stream_events=True, yield_run_output=True, **kwargs)
    if mode == "run_stream":
        events = list(owner.run(prompt, **stream_kwargs))
    else:
        events = [event async for event in owner.arun(prompt, **stream_kwargs)]
    return [event for event in events if isinstance(event, output_type)][-1]


async def _run_path(workflow: Any, use_async: bool, stream: bool, **kwargs: Any) -> WorkflowRunOutput:
    """Run a workflow on one of its four paths and return the final run output."""
    if not stream:
        return await workflow.arun(**kwargs) if use_async else workflow.run(**kwargs)
    if use_async:
        events = [event async for event in workflow.arun(stream=True, **kwargs)]
    else:
        events = list(workflow.run(stream=True, **kwargs))
    completed = [e for e in events if isinstance(e, WorkflowCompletedEvent)]
    assert len(completed) == 1
    return completed[0].run_output


def _reports(out: Union[RunOutput, TeamRunOutput]) -> List[Message]:
    """The re-entry reports the gate appended to a run's transcript."""
    return [m for m in (out.messages or []) if is_verification_report(m)]


def fail_once() -> Callable[[Any], Any]:
    """A check that fails its first call and passes every later one."""
    calls = {"n": 0}

    def report_exists(run_output):
        calls["n"] += 1
        return True if calls["n"] > 1 else "report.md is missing"

    return report_exists


def always_pass(run_output):
    return True


def always_fail(run_output):
    return "never good enough"


def _verification_records(step_results) -> List[Any]:
    """Every verification record in a run's step results, nested outputs included."""
    records = []

    def walk(outputs):
        for output in outputs or []:
            record = getattr(output, "verification", None)
            if record is not None:
                records.append(record)
            walk(getattr(output, "steps", None))

    walk(step_results)
    return records


def releasable_verifier() -> Tuple[Dict[str, bool], Callable[[Any], Any]]:
    """A verifier that fails until the test flips the switch: the first run exhausts its
    budget, the continuation passes."""
    state = {"pass": False}

    def check(run_output):
        return True if state["pass"] else "not good enough"

    return state, check


@tool(requires_confirmation=True)
def gated_probe() -> str:
    """A confirmation-gated tool: the run pauses on it."""
    return "probed"


def _confirmed(requirements) -> List[RunRequirement]:
    """Round-trip requirements through their wire format and confirm them, the way a
    frontend or a fresh process would send them back."""
    confirmed = []
    for data in [r.to_dict() for r in requirements or []]:
        req = RunRequirement.from_dict(data)
        req.confirm()
        confirmed.append(req)
    return confirmed
