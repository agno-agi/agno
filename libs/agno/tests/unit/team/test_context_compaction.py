from types import SimpleNamespace
from typing import AsyncIterator, Iterator

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.run.messages import RunMessages
from agno.run.team import TeamRunOutput
from agno.session import ContextCompactionManager
from agno.session.team import TeamSession
from agno.team import _messages
from agno.team.team import Team


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


def test_team_run_messages_auto_compact_history():
    primary_model = StubModel(token_count=500, response_text="primary response")
    compaction_model = StubModel(response_text="Compacted team summary")
    team = Team(
        members=[],
        model=primary_model,
        add_history_to_context=True,
        add_session_summary_to_context=True,
        context_compaction_manager=ContextCompactionManager(
            model=compaction_model,
            compact_token_limit=100,
            keep_last_n_runs=1,
        ),
    )

    session = TeamSession(
        session_id="session-1",
        runs=[
            TeamRunOutput(
                run_id="run-1",
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="Older team question"),
                    Message(role="assistant", content="Older team answer"),
                ],
            ),
            TeamRunOutput(
                run_id="run-2",
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="Middle team question"),
                    Message(role="assistant", content="Middle team answer"),
                ],
            ),
            TeamRunOutput(
                run_id="run-3",
                status=RunStatus.completed,
                messages=[
                    Message(role="user", content="Recent team question"),
                    Message(role="assistant", content="Recent team answer"),
                ],
            ),
        ],
    )
    run_context = RunContext(run_id="run-4", session_id="session-1", user_id="user-1")
    run_response = TeamRunOutput(run_id="run-4")

    run_messages: RunMessages = _messages._get_run_messages(
        team,
        run_response=run_response,
        run_context=run_context,
        session=session,
        input_message="Newest team question",
        add_history_to_context=True,
    )

    assert session.summary is not None
    assert session.summary.summary == "Compacted team summary"
    assert session.get_last_compacted_run_id() == "run-2"
    assert run_messages.system_message is not None
    assert "Compacted team summary" in str(run_messages.system_message.content)

    prompt_text = "\n".join(str(message.content) for message in run_messages.messages if message.content is not None)
    assert "Older team question" not in prompt_text
    assert "Middle team question" not in prompt_text
    assert "Recent team question" in prompt_text
    assert "Newest team question" in prompt_text
    assert len(compaction_model.calls) == 1
