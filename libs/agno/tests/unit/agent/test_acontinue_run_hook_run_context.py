"""Tool hooks on a continued run must see the current transcript.

``_build_continue_run_messages`` publishes the rebuilt message list on
``run_context.messages`` so tool hooks can read the conversation that led to
the proposal they are about to run. The sync continue path passes its
``run_context`` to the builder; the async paths must do the same, otherwise a
hook that runs during ``acontinue_run`` sees ``None`` where ``continue_run``
gives it the transcript.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunContext, RunStatus
from agno.tools.decorator import tool


class _ProposeThenFinishModel(Model):
    """Propose one confirmation-gated call, then finish after its result."""

    def __init__(self) -> None:
        super().__init__(id="hook-context", name="hook-context", provider="test")
        self.calls = 0

    def _next_response(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    {
                        "id": "proposal-1",
                        "type": "function",
                        "function": {"name": "present_for_review", "arguments": '{"artifact": "draft-v1"}'},
                    }
                ]
            )
        return ModelResponse(content="done")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next_response()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next_response()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _agent_with_hook(hook_contexts: list[list[Message] | None]) -> tuple[Agent, list[str]]:
    executions: list[str] = []

    def record_hook_context(run_context: RunContext) -> None:
        hook_contexts.append(list(run_context.messages) if run_context.messages is not None else None)

    @tool(requires_confirmation=True, pre_hook=record_hook_context)
    def present_for_review(artifact: str) -> str:
        executions.append(f"present:{artifact}")
        return "presented"

    return Agent(model=_ProposeThenFinishModel(), tools=[present_for_review], telemetry=False), executions


def _confirm(paused: RunOutput) -> RunOutput:
    persisted = RunOutput.from_dict(paused.to_dict())
    assert persisted.status == RunStatus.paused
    assert persisted.tools and len(persisted.tools) == 1
    persisted.tools[0].confirmed = True
    return persisted


def _assert_hook_saw_transcript(hook_contexts: list[list[Message] | None], initial_input: str) -> None:
    assert len(hook_contexts) == 1
    messages = hook_contexts[0]
    assert messages is not None, "hook received run_context.messages=None on continue"
    assert any(message.role == "user" and message.content == initial_input for message in messages)
    assert any(
        message.role == "assistant" and message.tool_calls and message.tool_calls[0]["id"] == "proposal-1"
        for message in messages
    )


@pytest.mark.parametrize("stream", [False, True])
def test_sync_continue_hook_receives_current_transcript(stream: bool) -> None:
    hook_contexts: list[list[Message] | None] = []
    agent, executions = _agent_with_hook(hook_contexts)
    initial_input = "Prepare the artifact for review."
    persisted = _confirm(agent.run(initial_input))

    if stream:
        events = list(agent.continue_run(persisted, stream=True, stream_events=True, yield_run_output=True))
        result = next(event for event in events if isinstance(event, RunOutput))
    else:
        result = agent.continue_run(persisted)

    assert result.status == RunStatus.completed
    assert executions == ["present:draft-v1"]
    _assert_hook_saw_transcript(hook_contexts, initial_input)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_async_continue_hook_receives_current_transcript(stream: bool) -> None:
    hook_contexts: list[list[Message] | None] = []
    agent, executions = _agent_with_hook(hook_contexts)
    initial_input = "Prepare the artifact for review."
    persisted = _confirm(await agent.arun(initial_input))

    if stream:
        events = [
            event
            async for event in agent.acontinue_run(persisted, stream=True, stream_events=True, yield_run_output=True)
        ]
        result = next(event for event in events if isinstance(event, RunOutput))
    else:
        result = await agent.acontinue_run(persisted)

    assert result.status == RunStatus.completed
    assert executions == ["present:draft-v1"]
    _assert_hook_saw_transcript(hook_contexts, initial_input)
