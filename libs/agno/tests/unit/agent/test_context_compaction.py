from types import SimpleNamespace
from typing import AsyncIterator, Iterator

from agno.agent import _messages
from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import ContextCompactionManager
from agno.session.agent import AgentSession


class StubModel(Model):
    supports_native_structured_outputs = False
    supports_json_schema_outputs = False

    def __init__(self, *, token_count: int = 0, response_text: str = "ok"):
        super().__init__(id="stub-model", name="stub-model", provider="test")
        self.token_count = token_count
        self.response_text = response_text
        self.calls = []

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    def count_tokens(self, messages, tools=None, output_schema=None):
        return self.token_count

    async def acount_tokens(self, messages, tools=None, output_schema=None):
        return self.token_count

    def response(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(content=self.response_text)

    async def aresponse(self, messages, **kwargs):
        return self.response(messages, **kwargs)

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(content=self.response_text)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(content=self.response_text)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield ModelResponse(content=self.response_text)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield ModelResponse(content=self.response_text)

    def _parse_provider_response(self, *args, **kwargs):
        return ModelResponse(content=self.response_text)

    def _parse_provider_response_delta(self, *args, **kwargs):
        return ModelResponse(content=self.response_text)


def test_agent_run_messages_auto_compact_history():
    primary_model = StubModel(token_count=500, response_text="primary response")
    compaction_model = StubModel(response_text="Compacted session summary")
    agent = Agent(
        model=primary_model,
        add_history_to_context=True,
        add_session_summary_to_context=True,
        context_compaction_manager=ContextCompactionManager(
            model=compaction_model,
            compact_token_limit=100,
            keep_last_n_runs=1,
        ),
    )

    session = AgentSession(
        session_id="session-1",
        runs=[
            RunOutput(
                run_id="run-1",
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="Older question"),
                    Message(role="assistant", content="Older answer"),
                ],
            ),
            RunOutput(
                run_id="run-2",
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="Middle question"),
                    Message(role="assistant", content="Middle answer"),
                ],
            ),
            RunOutput(
                run_id="run-3",
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="Recent question"),
                    Message(role="assistant", content="Recent answer"),
                ],
            ),
        ],
    )
    run_context = RunContext(run_id="run-4", session_id="session-1", user_id="user-1")
    run_response = RunOutput(run_id="run-4")

    run_messages = _messages.get_run_messages(
        agent,
        run_response=run_response,
        run_context=run_context,
        input="Newest question",
        session=session,
        add_history_to_context=True,
    )

    assert session.summary is not None
    assert session.summary.summary == "Compacted session summary"
    assert session.get_last_compacted_run_id() == "run-2"
    assert run_messages.system_message is not None
    assert "Compacted session summary" in str(run_messages.system_message.content)

    prompt_text = "\n".join(str(message.content) for message in run_messages.messages if message.content is not None)
    assert "Older question" not in prompt_text
    assert "Middle question" not in prompt_text
    assert "Recent question" in prompt_text
    assert "Newest question" in prompt_text
    assert len(compaction_model.calls) == 1
