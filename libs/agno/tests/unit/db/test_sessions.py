from agno.session.agent import AgentSession
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
