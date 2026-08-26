"""TeamRunErrorEvent.error_type is populated on generic (non-guardrail) failures.

Twin of tests/unit/agent/test_run_error_event_type.py for the team run paths.
"""

from typing import Any, AsyncIterator, Iterator

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.team import Team


class ExplodingModel(Model):
    def __init__(self) -> None:
        super().__init__(id="exploding", name="exploding", provider="test")

    def __deepcopy__(self, memo: dict) -> "ExplodingModel":
        return type(self)()

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise RuntimeError("boom")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise RuntimeError("boom")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _team() -> Team:
    member = Agent(name="member", model=ExplodingModel(), telemetry=False)
    return Team(members=[member], model=ExplodingModel(), telemetry=False)


def test_sync_stream_team_error_event_carries_class_name():
    events = list(_team().run(input="hi", stream=True, stream_events=True))
    error_events = [event for event in events if isinstance(event, TeamRunErrorEvent)]
    assert error_events
    assert all(event.error_type == "RuntimeError" for event in error_events)


async def test_async_stream_team_error_event_carries_class_name():
    events = [event async for event in _team().arun(input="hi", stream=True, stream_events=True)]
    error_events = [event for event in events if isinstance(event, TeamRunErrorEvent)]
    assert error_events
    assert all(event.error_type == "RuntimeError" for event in error_events)
