"""A model stream that fails partway is retried from scratch.

What the failed attempt already streamed must be dropped: otherwise its tool calls run
together with the retry's tool calls and its text is repeated in the run output.
"""

from typing import Any, AsyncIterator, Iterator, List, Optional, Union

from agno.agent.agent import Agent
from agno.exceptions import ModelProviderError, RetryableModelProviderError
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team.team import Team

Attempt = List[Union[ModelResponse, Exception]]
PICKUP = {"name": "add_line_item", "arguments": '{"description": "Pickup"}'}
AIRFREIGHT = {"name": "add_line_item", "arguments": '{"description": "Airfreight"}'}


class ScriptedStreamModel(Model):
    """Streams one scripted attempt per call; an exception in an attempt fails that stream at that point."""

    def __init__(self, attempts: List[Attempt]):
        super().__init__(id="scripted", name="scripted", provider="test", retries=1, delay_between_retries=0)
        self.attempts = attempts

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        for item in self.attempts.pop(0):
            if isinstance(item, Exception):
                raise item
            yield item

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        for item in self.attempts.pop(0):
            if isinstance(item, Exception):
                raise item
            yield item

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def two_requests_each_failing_once() -> List[Attempt]:
    overloaded = ModelProviderError("Overloaded", status_code=503)
    return [
        # Request 1: one finished tool call, then the stream fails
        [
            ModelResponse(content="Adding the items. "),
            ModelResponse(tool_calls=[{"id": "call_a1", "type": "function", "function": PICKUP}]),
            overloaded,
        ],
        # Request 1, retried: the model plans the same call again, plus a second one
        [
            ModelResponse(content="Adding the items. "),
            ModelResponse(
                tool_calls=[
                    {"id": "call_b1", "type": "function", "function": PICKUP},
                    {"id": "call_b2", "type": "function", "function": AIRFREIGHT},
                ]
            ),
        ],
        # Request 2 (after the tool results): fails partway through the text
        [ModelResponse(content="Both ite"), overloaded],
        # Request 2, retried
        [ModelResponse(content="Both items added.")],
    ]


def make_agent(model: Model, executed: List[str]) -> Agent:
    def add_line_item(description: str) -> str:
        """Add a line item to the quote."""
        executed.append(description)
        return f"added {description}"

    return Agent(model=model, tools=[add_line_item], telemetry=False)


def assert_failed_attempts_discarded(
    run_output: Optional[RunOutput], executed: List[str], model: ScriptedStreamModel
) -> None:
    assert run_output is not None
    assert model.attempts == []
    assert executed == ["Pickup", "Airfreight"]
    assert run_output.content == "Adding the items. Both items added."
    assistant_messages = [m for m in run_output.messages if m.role == "assistant"]
    assert [m.content for m in assistant_messages] == ["Adding the items. ", "Both items added."]
    assert [tc["id"] for tc in assistant_messages[0].tool_calls] == ["call_b1", "call_b2"]


def test_agent_stream_retry_discards_failed_attempt():
    model = ScriptedStreamModel(two_requests_each_failing_once())
    executed: List[str] = []
    agent = make_agent(model, executed)

    run_output = None
    for event in agent.run("Add Pickup and Airfreight to the quote.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            run_output = event

    assert_failed_attempts_discarded(run_output, executed, model)


async def test_agent_async_stream_retry_discards_failed_attempt():
    model = ScriptedStreamModel(two_requests_each_failing_once())
    executed: List[str] = []
    agent = make_agent(model, executed)

    run_output = None
    async for event in agent.arun("Add Pickup and Airfreight to the quote.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            run_output = event

    assert_failed_attempts_discarded(run_output, executed, model)


def test_agent_stream_retry_with_guidance_discards_failed_attempt():
    model = ScriptedStreamModel(
        [
            [
                ModelResponse(content="Draft "),
                RetryableModelProviderError(retry_guidance_message="Call the tool correctly.", original_error="bad"),
            ],
            [ModelResponse(content="Final answer.")],
        ]
    )
    agent = Agent(model=model, telemetry=False)

    run_output = None
    for event in agent.run("Answer.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            run_output = event

    assert run_output is not None
    assert run_output.content == "Final answer."


async def test_agent_async_stream_retry_with_guidance_discards_failed_attempt():
    model = ScriptedStreamModel(
        [
            [
                ModelResponse(content="Draft "),
                RetryableModelProviderError(retry_guidance_message="Call the tool correctly.", original_error="bad"),
            ],
            [ModelResponse(content="Final answer.")],
        ]
    )
    agent = Agent(model=model, telemetry=False)

    run_output = None
    async for event in agent.arun("Answer.", stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            run_output = event

    assert run_output is not None
    assert run_output.content == "Final answer."


def test_team_stream_retry_discards_failed_attempt():
    member = Agent(name="Member", model=ScriptedStreamModel([]), telemetry=False)
    model = ScriptedStreamModel(
        [
            [ModelResponse(content="Hel"), ModelProviderError("Overloaded", status_code=503)],
            [ModelResponse(content="Hello there.")],
        ]
    )
    team = Team(members=[member], model=model, telemetry=False)

    run_output = None
    for event in team.run("Say hello.", stream=True, yield_run_output=True):
        if isinstance(event, TeamRunOutput):
            run_output = event

    assert run_output is not None
    assert run_output.content == "Hello there."


async def test_team_async_stream_retry_discards_failed_attempt():
    member = Agent(name="Member", model=ScriptedStreamModel([]), telemetry=False)
    model = ScriptedStreamModel(
        [
            [ModelResponse(content="Hel"), ModelProviderError("Overloaded", status_code=503)],
            [ModelResponse(content="Hello there.")],
        ]
    )
    team = Team(members=[member], model=model, telemetry=False)

    run_output = None
    async for event in team.arun("Say hello.", stream=True, yield_run_output=True):
        if isinstance(event, TeamRunOutput):
            run_output = event

    assert run_output is not None
    assert run_output.content == "Hello there."
