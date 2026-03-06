import time

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
