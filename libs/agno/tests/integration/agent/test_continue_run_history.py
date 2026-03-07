import time
from typing import Any, AsyncIterator, Iterator

import pytest
from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


class DummyModel(Model):
    """A minimal model that records the messages it receives."""

    def __init__(self):
        super().__init__(id="dummy", name="Dummy", provider="Dummy")
        self.last_messages = None

    def invoke(self, *, messages, **kwargs) -> ModelResponse:  # type: ignore[override]
        self.last_messages = messages
        return ModelResponse(content="ok")

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        messages = kwargs.get("messages")
        self.last_messages = messages
        return ModelResponse(content="ok")

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        messages = kwargs.get("messages")
        self.last_messages = messages
        yield ModelResponse(content="ok")

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        messages = kwargs.get("messages")
        self.last_messages = messages
        yield ModelResponse(content="ok")
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return ModelResponse(content="ok")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse(content="ok")


def test_continue_run_adds_history_to_context(shared_db):
    model = DummyModel()
    agent = Agent(
        model=model,
        db=shared_db,
        add_history_to_context=True,
        num_history_runs=1,
        telemetry=False,
    )

    session_id = "s1"

    # First run creates history in the session.
    agent.run("hello", session_id=session_id)

    # Continue-run uses a separate run_response (e.g. a paused HITL tool call) and should include history.
    paused_run = RunOutput(
        run_id="run-2",
        session_id=session_id,
        agent_id=agent.id,
        status=RunStatus.paused,
        created_at=int(time.time()),
        messages=[
            Message(role="user", content="second question"),
        ],
    )

    agent.continue_run(paused_run)

    assert model.last_messages is not None
    contents = [m.content for m in model.last_messages if getattr(m, "content", None)]
    assert any("hello" in str(c) for c in contents), (
        "History messages from prior runs are included in continue_run's context"
    )


@pytest.mark.asyncio
async def test_acontinue_run_adds_history_to_context(shared_db):
    model = DummyModel()
    agent = Agent(
        model=model,
        db=shared_db,
        add_history_to_context=True,
        num_history_runs=1,
        telemetry=False,
    )

    session_id = "s2"

    # First run creates history in the session.
    agent.run("hello async", session_id=session_id)

    paused_run = RunOutput(
        run_id="run-3",
        session_id=session_id,
        agent_id=agent.id,
        status=RunStatus.paused,
        created_at=int(time.time()),
        messages=[
            Message(role="user", content="second async question"),
        ],
    )

    await agent.acontinue_run(paused_run)

    assert model.last_messages is not None
    contents = [m.content for m in model.last_messages if getattr(m, "content", None)]
    assert any("hello async" in str(c) for c in contents), (
        "History messages from prior runs are included in acontinue_run's context"
    )


@pytest.mark.asyncio
async def test_acontinue_run_stream_adds_history_to_context(shared_db):
    model = DummyModel()
    agent = Agent(
        model=model,
        db=shared_db,
        add_history_to_context=True,
        num_history_runs=1,
        telemetry=False,
    )

    session_id = "s3"

    # First run creates history in the session.
    agent.run("hello async stream", session_id=session_id)

    paused_run = RunOutput(
        run_id="run-4",
        session_id=session_id,
        agent_id=agent.id,
        status=RunStatus.paused,
        created_at=int(time.time()),
        messages=[
            Message(role="user", content="second async stream question"),
        ],
    )

    async for _ in agent.acontinue_run(paused_run, stream=True):
        pass

    assert model.last_messages is not None
    contents = [m.content for m in model.last_messages if getattr(m, "content", None)]
    assert any("hello async stream" in str(c) for c in contents), (
        "History messages from prior runs are included in acontinue_run's context with stream set to true"
    )
