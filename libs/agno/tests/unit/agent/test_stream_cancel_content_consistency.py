"""A streaming run cancelled mid-stream must not persist content it never streamed. The
model stream commits each delta to run_response.content before the cancel check yielded
it, so cancelling before the yield dropped that delta's RunContent event while keeping its
content -> the reconstructed stream diverged from the final RunOutput.content."""

from typing import Any, AsyncIterator, Iterator


from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput


class _ScriptedModel(Model):
    def __init__(self, deltas):
        super().__init__(id="m", name="m", provider="test")
        self._deltas = deltas

    def invoke(self, *a, **k):
        raise NotImplementedError

    async def ainvoke(self, *a, **k):
        raise NotImplementedError

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield from self._deltas

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        for d in self._deltas:
            yield d
        return

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _deltas():
    return [ModelResponse(content=w + " ", role="assistant") for w in ["one", "two", "three", "four", "five"]]


def test_stream_cancel_content_matches_delivered_events():
    agent = Agent(model=_ScriptedModel(_deltas()), telemetry=False)

    seen = []
    run_output = None
    for event in agent.run("go", stream=True, stream_events=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            run_output = event
            continue
        if event.event == "RunContent":
            seen.append(event.content)
            if len(seen) == 2:
                agent.cancel_run(event.run_id)

    # The persisted content must equal what was actually streamed (no un-emitted trailing delta).
    assert "".join(seen) == run_output.content
