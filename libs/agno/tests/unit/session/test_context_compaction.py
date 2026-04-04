from types import SimpleNamespace
from unittest.mock import patch

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from agno.session.compaction import ContextCompactionManager


class StubModel(Model):
    supports_native_structured_outputs = False
    supports_json_schema_outputs = False

    def __init__(self, response_text: str = "Compacted summary"):
        super().__init__(id="stub-model", name="stub-model", provider="test")
        self.response_text = response_text
        self.calls = []

    def response(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(content=self.response_text)

    async def aresponse(self, messages, **kwargs):
        return self.response(messages, **kwargs)

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(content=self.response_text)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(content=self.response_text)

    def invoke_stream(self, *args, **kwargs):
        yield ModelResponse(content=self.response_text)

    async def ainvoke_stream(self, *args, **kwargs):
        yield ModelResponse(content=self.response_text)

    def _parse_provider_response(self, *args, **kwargs):
        return ModelResponse(content=self.response_text)

    def _parse_provider_response_delta(self, *args, **kwargs):
        return ModelResponse(content=self.response_text)


def _build_session() -> AgentSession:
    from agno.models.message import Message

    runs = [
        RunOutput(
            run_id="run-1",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Discuss the architecture."),
                Message(role="assistant", content="We should use a queue."),
            ],
        ),
        RunOutput(
            run_id="run-2",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Add retries too."),
                Message(role="assistant", content="Retries will be exponential."),
            ],
        ),
        RunOutput(
            run_id="run-3",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Keep the last run detailed."),
                Message(role="assistant", content="Recent details stay uncompressed."),
            ],
        ),
    ]
    return AgentSession(session_id="session-1", runs=runs)


def test_context_compaction_updates_summary_and_cutoff():
    manager = ContextCompactionManager(model=StubModel("Compacted architecture summary"), keep_last_n_runs=1)
    session = _build_session()

    compacted = manager.compact_session(session)

    assert compacted is True
    assert session.summary is not None
    assert session.summary.summary == "Compacted architecture summary"
    assert session.get_last_compacted_run_id() == "run-2"

    remaining_messages = session.get_messages(after_run_id=session.get_last_compacted_run_id())
    remaining_contents = [message.content for message in remaining_messages if isinstance(message.content, str)]
    assert "Keep the last run detailed." in remaining_contents
    assert "Discuss the architecture." not in remaining_contents


def test_context_compaction_resolves_model_strings():
    resolved_model = StubModel("Resolved external model summary")
    session = _build_session()

    with patch("agno.session.compaction.get_model", return_value=resolved_model) as get_model:
        manager = ContextCompactionManager(model="openrouter:openai/gpt-4o-mini", keep_last_n_runs=1)

        compacted = manager.compact_session(session)

    assert compacted is True
    assert session.summary is not None
    assert session.summary.summary == "Resolved external model summary"
    get_model.assert_called_once_with("openrouter:openai/gpt-4o-mini")
