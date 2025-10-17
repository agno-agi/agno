import json

from agno.session.agent import AgentSession
from agno.run.agent import RunOutput
from agno.session.summary import SessionSummary
from agno.session.exporter import export_session_to_dict, export_session_to_json, export_session_to_markdown


def _make_simple_session():
    s = AgentSession(session_id="s1", agent_id="agent1", user_id="user1", session_data={"key": "value"})
    r = RunOutput(run_id="r1", session_id="s1", agent_id="agent1", content="response text")
    # Add a minimal message-like object
    from agno.models.message import Message

    r.messages = [Message(role="user", content="hello"), Message(role="assistant", content="world")]
    s.runs = [r]
    s.summary = SessionSummary(summary="short summary")
    return s


def test_export_dict_contains_expected_fields():
    s = _make_simple_session()
    d = export_session_to_dict(s)
    assert d["session_id"] == "s1"
    assert d["agent_id"] == "agent1"
    assert "runs" in d and isinstance(d["runs"], list)
    assert d["summary"]["summary"] == "short summary"


def test_export_json_and_markdown():
    s = _make_simple_session()
    js = export_session_to_json(s, pretty=False)
    # should be valid json
    parsed = json.loads(js)
    assert parsed["session_id"] == "s1"

    md = export_session_to_markdown(s)
    assert "# Session s1" in md
    assert "short summary" in md
    assert "hello" in md and "world" in md
