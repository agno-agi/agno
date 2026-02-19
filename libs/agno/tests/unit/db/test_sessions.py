import json
from datetime import datetime

from agno.db.utils import CustomJSONEncoder, json_serializer, serialize_session_json_fields
from agno.session.agent import AgentSession
from agno.session.summary import SessionSummary
from agno.session.team import TeamSession


def test_agent_session_serialization_empty_runs():
    sess1 = AgentSession(session_id="s3", runs=[])
    dump = sess1.to_dict()
    sess2 = AgentSession.from_dict(dump)
    assert sess1 == sess2


def test_team_session_serialization_empty_runs():
    sess1 = TeamSession(session_id="s3", runs=[])
    dump = sess1.to_dict()
    sess2 = TeamSession.from_dict(dump)
    assert sess1 == sess2


def test_agent_session_to_dict_with_summary():
    """SessionSummary should be serialized to a JSON-safe dict by to_dict()."""
    summary = SessionSummary(
        summary="Test summary",
        topics=["topic1", "topic2"],
        updated_at=datetime(2026, 1, 15, 12, 0, 0),
    )
    session = AgentSession(session_id="s1", agent_id="a1", summary=summary, runs=[])
    d = session.to_dict()

    assert isinstance(d["summary"], dict)
    assert d["summary"]["summary"] == "Test summary"
    assert d["summary"]["topics"] == ["topic1", "topic2"]
    assert d["summary"]["updated_at"] == "2026-01-15T12:00:00"

    # Must be fully JSON-serializable with the standard encoder
    json_str = json.dumps(d)
    assert "Test summary" in json_str


def test_team_session_to_dict_with_summary():
    """SessionSummary should be serialized to a JSON-safe dict by to_dict()."""
    summary = SessionSummary(
        summary="Team summary",
        topics=["teamwork"],
        updated_at=datetime(2026, 2, 20, 10, 30, 0),
    )
    session = TeamSession(session_id="s2", team_id="t1", summary=summary, runs=[])
    d = session.to_dict()

    assert isinstance(d["summary"], dict)
    assert d["summary"]["summary"] == "Team summary"
    assert d["summary"]["updated_at"] == "2026-02-20T10:30:00"

    json_str = json.dumps(d)
    assert "Team summary" in json_str


def test_agent_session_roundtrip_with_summary():
    """SessionSummary should survive a to_dict / from_dict round-trip."""
    summary = SessionSummary(
        summary="Round-trip summary",
        topics=["a", "b"],
        updated_at=datetime(2026, 3, 1, 8, 0, 0),
    )
    sess1 = AgentSession(session_id="s4", agent_id="a1", summary=summary, runs=[])
    dump = sess1.to_dict()
    sess2 = AgentSession.from_dict(dump)

    assert sess2 is not None
    assert sess2.summary is not None
    assert isinstance(sess2.summary, SessionSummary)
    assert sess2.summary.summary == "Round-trip summary"
    assert sess2.summary.topics == ["a", "b"]
    assert sess2.summary.updated_at == datetime(2026, 3, 1, 8, 0, 0)


def test_team_session_roundtrip_with_summary():
    """SessionSummary should survive a to_dict / from_dict round-trip on TeamSession."""
    summary = SessionSummary(
        summary="Team round-trip",
        topics=["x"],
        updated_at=datetime(2026, 4, 1, 9, 0, 0),
    )
    sess1 = TeamSession(session_id="s5", team_id="t1", summary=summary, runs=[])
    dump = sess1.to_dict()
    sess2 = TeamSession.from_dict(dump)

    assert sess2 is not None
    assert sess2.summary is not None
    assert isinstance(sess2.summary, SessionSummary)
    assert sess2.summary.summary == "Team round-trip"


def test_custom_json_encoder_handles_session_summary():
    """CustomJSONEncoder should serialize SessionSummary objects."""
    summary = SessionSummary(
        summary="Encoder test",
        topics=["t1"],
        updated_at=datetime(2026, 5, 1, 0, 0, 0),
    )
    result = json.dumps({"summary": summary}, cls=CustomJSONEncoder)
    parsed = json.loads(result)
    assert parsed["summary"]["summary"] == "Encoder test"
    assert parsed["summary"]["updated_at"] == "2026-05-01T00:00:00"


def test_custom_json_encoder_handles_session_summary_directly():
    """CustomJSONEncoder should serialize a standalone SessionSummary."""
    summary = SessionSummary(summary="Direct test", topics=None, updated_at=None)
    result = json.dumps(summary, cls=CustomJSONEncoder)
    parsed = json.loads(result)
    assert parsed["summary"] == "Direct test"
    assert "topics" not in parsed  # None values excluded by to_dict


def test_json_serializer_handles_session_summary():
    """json_serializer (used by PostgreSQL engine) should handle SessionSummary."""
    summary = SessionSummary(
        summary="PG test",
        topics=["pg"],
        updated_at=datetime(2026, 6, 1, 12, 0, 0),
    )
    result = json_serializer({"summary": summary})
    parsed = json.loads(result)
    assert parsed["summary"]["summary"] == "PG test"


def test_serialize_session_json_fields_with_summary_object():
    """serialize_session_json_fields should convert SessionSummary objects to JSON strings."""
    summary = SessionSummary(
        summary="Serialize test",
        topics=["s1"],
        updated_at=datetime(2026, 7, 1, 0, 0, 0),
    )
    session_dict = {
        "summary": summary,
        "session_data": None,
        "agent_data": None,
        "team_data": None,
        "workflow_data": None,
        "metadata": None,
        "chat_history": None,
        "runs": None,
    }
    result = serialize_session_json_fields(session_dict)
    assert isinstance(result["summary"], str)
    parsed = json.loads(result["summary"])
    assert parsed["summary"] == "Serialize test"
    assert parsed["updated_at"] == "2026-07-01T00:00:00"


def test_serialize_session_json_fields_with_summary_dict():
    """serialize_session_json_fields should also handle summary as a plain dict."""
    session_dict = {
        "summary": {"summary": "Dict test", "topics": ["d1"]},
        "session_data": None,
        "agent_data": None,
        "team_data": None,
        "workflow_data": None,
        "metadata": None,
        "chat_history": None,
        "runs": None,
    }
    result = serialize_session_json_fields(session_dict)
    assert isinstance(result["summary"], str)
    parsed = json.loads(result["summary"])
    assert parsed["summary"] == "Dict test"


def test_session_summary_none_does_not_break():
    """Sessions with summary=None should serialize without errors."""
    session = AgentSession(session_id="s6", runs=[], summary=None)
    d = session.to_dict()
    assert d["summary"] is None
    json_str = json.dumps(d)
    assert '"summary": null' in json_str
