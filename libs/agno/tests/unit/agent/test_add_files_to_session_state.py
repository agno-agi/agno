"""Unit tests for Agent.add_files_to_session_state and the file-recording helper."""

from agno.agent.agent import Agent
from agno.agent._messages import _add_files_to_session_state
from agno.media import File
from agno.models.openai import OpenAIResponses
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
    _add_files_to_session_state(
        agent, ctx, [File(id="f1", filename="report.xlsx", mime_type="text/csv")]
    )
    assert ctx.session_state == {
        "uploaded_files": [{"id": "f1", "filename": "report.xlsx", "mime_type": "text/csv"}]
    }


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
    assert ctx.session_state == {
        "uploaded_files": [{"id": "f1", "filename": "a.csv", "mime_type": "text/csv"}]
    }


def test_dedup_by_filename_mime_when_no_id():
    agent = _agent(add_files_to_session_state=True, send_media_to_model=False)
    ctx = _ctx()
    _add_files_to_session_state(agent, ctx, [File(url="https://x", filename="a.csv", mime_type="text/csv")])
    _add_files_to_session_state(agent, ctx, [File(url="https://y", filename="a.csv", mime_type="text/csv")])
    assert ctx.session_state == {
        "uploaded_files": [{"filename": "a.csv", "mime_type": "text/csv"}]
    }


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
