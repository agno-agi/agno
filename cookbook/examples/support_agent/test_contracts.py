"""Actual Agno retrieval, references, session history, and local handoff."""

import importlib
import sys

from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb


def test_retrieval_followup_handoff_and_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("support_agent", None)
    module = importlib.import_module("support_agent")
    from fixture_model import fixture_model

    module.agent.model = fixture_model()
    first = module.agent.run(
        "How do I export a workspace?", user_id="alice", session_id="support"
    )
    second = module.agent.run(
        "Can a member do that too?", user_id="alice", session_id="support"
    )
    last = module.agent.run(
        "Can exports stay in Germany by contract?",
        user_id="alice",
        session_id="support",
    )
    for result in [first, second]:
        assert isinstance(result.content, module.SupportAnswer)
        refs = {
            doc["meta_data"]["source"]
            for group in result.references
            for doc in group.references
        }
        assert set(result.content.sources) <= refs
        assert "docs/exports.md" in refs
    assert any("How do I export" in str(message.content) for message in second.messages)
    assert last.content.status == "needs_human"
    assert "Germany" in last.content.handoff.question
    restarted = SqliteDb(db_file="tmp/support_agent.db")
    saved = restarted.get_session(session_id="support", session_type=SessionType.AGENT)
    assert len(saved.runs) == 3
    assert saved.runs[-1].content["handoff"]["unresolved"]
    assert module.retrieve_docs("zyzzyva") == []
