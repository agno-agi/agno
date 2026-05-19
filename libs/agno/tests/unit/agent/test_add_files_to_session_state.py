"""Unit tests for Agent.add_files_to_session_state and the file-recording helper."""

from typing import Any, AsyncIterator, Iterator
from unittest.mock import AsyncMock, Mock

from agno.agent.agent import Agent
from agno.agent._messages import _add_files_to_session_state
from agno.media import File
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.openai import OpenAIResponses
from agno.models.response import ModelResponse
from agno.run import RunContext


def _agent(**kwargs) -> Agent:
    return Agent(model=OpenAIResponses(id="gpt-5.4"), **kwargs)


def _ctx() -> RunContext:
    return RunContext(run_id="r1", session_id="s1")


def test_field_defaults_false():
    agent = _agent()
    assert agent.add_files_to_session_state is False


def test_field_can_be_enabled():
    agent = _agent(add_files_to_session_state=True)
    assert agent.add_files_to_session_state is True


def test_noop_when_flag_off():
    agent = _agent(add_files_to_session_state=False, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(id="f1", filename="a.csv", mime_type="text/csv")])
    assert ctx.session_state is None


def test_noop_when_send_media_to_model_true():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=True)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(id="f1", filename="a.csv", mime_type="text/csv")])
    assert ctx.session_state is None


def test_noop_when_no_files():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, None)
    assert ctx.session_state is None
    _add_files_to_session_state(agent, ctx, [])
    assert ctx.session_state is None


def test_records_id_filename_mime_type():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(id="f1", filename="report.xlsx", mime_type="text/csv")])
    assert ctx.session_state == {"uploaded_files": [{"id": "f1", "filename": "report.xlsx", "mime_type": "text/csv"}]}


def test_none_fields_dropped_and_name_fallback():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(url="https://x/y", name="doc.pdf")])
    assert ctx.session_state == {"uploaded_files": [{"filename": "doc.pdf"}]}


def test_empty_entry_skipped():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(url="https://x/y")])
    assert ctx.session_state == {"uploaded_files": []}


def test_dedup_by_id():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(id="f1", filename="a.csv", mime_type="text/csv")])
    _add_files_to_session_state(agent, ctx, [File(id="f1", filename="renamed.csv", mime_type="text/csv")])
    assert ctx.session_state == {"uploaded_files": [{"id": "f1", "filename": "a.csv", "mime_type": "text/csv"}]}


def test_dedup_by_filename_mime_when_no_id():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(url="https://x", filename="a.csv", mime_type="text/csv")])
    _add_files_to_session_state(agent, ctx, [File(url="https://y", filename="a.csv", mime_type="text/csv")])
    assert ctx.session_state == {"uploaded_files": [{"filename": "a.csv", "mime_type": "text/csv"}]}


def test_accumulates_distinct_files_in_order():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(id="f1", filename="a.csv", mime_type="text/csv")])
    _add_files_to_session_state(agent, ctx, [File(id="f2", filename="b.csv", mime_type="text/csv")])
    assert ctx.session_state == {
        "uploaded_files": [
            {"id": "f1", "filename": "a.csv", "mime_type": "text/csv"},
            {"id": "f2", "filename": "b.csv", "mime_type": "text/csv"},
        ]
    }


class _MockModel(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._resp = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())
        self.response = Mock(return_value=self._resp)
        self.aresponse = AsyncMock(return_value=self._resp)

    def get_instructions_for_model(self, *a, **k):
        return None

    def get_system_message_for_model(self, *a, **k):
        return None

    async def aget_instructions_for_model(self, *a, **k):
        return None

    async def aget_system_message_for_model(self, *a, **k):
        return None

    def parse_args(self, *a, **k):
        return {}

    def invoke(self, *a, **k):
        return self._resp

    async def ainvoke(self, *a, **k):
        return self._resp

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._resp

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._resp
        return

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return self._resp

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._resp


def test_sync_run_populates_uploaded_files():
    agent = Agent(
        model=_MockModel(),
        add_files_to_session_state=True,
        send_media_to_model=False,
    )
    resp = agent.run("process this", files=[File(id="f1", filename="a.csv", mime_type="text/csv")])
    assert resp.session_state is not None
    assert resp.session_state.get("uploaded_files") == [{"id": "f1", "filename": "a.csv", "mime_type": "text/csv"}]


async def test_async_run_populates_uploaded_files():
    agent = Agent(
        model=_MockModel(),
        add_files_to_session_state=True,
        send_media_to_model=False,
    )
    resp = await agent.arun("process this", files=[File(id="f2", filename="b.csv", mime_type="text/csv")])
    assert resp.session_state is not None
    assert resp.session_state.get("uploaded_files") == [{"id": "f2", "filename": "b.csv", "mime_type": "text/csv"}]


def test_preserves_other_session_state_keys():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    ctx.session_state = {"foo": "bar"}
    _add_files_to_session_state(agent, ctx, [File(id="f1", filename="a.csv", mime_type="text/csv")])
    assert ctx.session_state["foo"] == "bar"
    assert ctx.session_state["uploaded_files"] == [{"id": "f1", "filename": "a.csv", "mime_type": "text/csv"}]


def test_overwrites_non_list_uploaded_files():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    ctx.session_state = {"uploaded_files": "not-a-list"}
    _add_files_to_session_state(agent, ctx, [File(id="f1", filename="a.csv", mime_type="text/csv")])
    assert ctx.session_state["uploaded_files"] == [{"id": "f1", "filename": "a.csv", "mime_type": "text/csv"}]
