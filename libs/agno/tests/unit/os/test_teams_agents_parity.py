"""Small teams/agents endpoint divergences: input robustness and log hygiene.

- One unparseable uploaded document must not 500 a team submission (agents
  skip the file and continue; teams processed it bare).
- The agents version param is an int like teams/workflows: the old str
  declaration with a bare int() cast 500ed on non-numeric input where the
  siblings answer a clean 422.
- The teams debug line logged raw message content (PII/secrets belong in
  the run record, not the log stream).
"""

import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.team import Team


@pytest.fixture()
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db)
    team = Team(id="qa-team", name="QA Team", members=[agent], db=db)
    app = AgentOS(agents=[agent], teams=[team], telemetry=False).get_app()
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=False))


@pytest.fixture()
def benign_team_run(monkeypatch):
    async def fake_arun(self, **kwargs):
        return SimpleNamespace(to_dict=lambda: {"run_id": "r1", "status": "COMPLETED"})

    monkeypatch.setattr(Team, "arun", fake_arun)


class TestBadDocumentIsSkipped:
    def test_unparseable_document_does_not_500_the_submission(self, harness, benign_team_run, monkeypatch):
        def broken_process_document(file):
            raise ValueError("unparseable document")

        monkeypatch.setattr("agno.os.routers.teams.router.process_document", broken_process_document)
        resp = harness.client.post(
            "/teams/qa-team/runs",
            data={"message": "hi", "stream": "false"},
            files={"files": ("bad.pdf", b"\x00garbage", "application/pdf")},
        )
        assert resp.status_code == 200, (
            f"one bad document must be skipped (agents parity), got {resp.status_code}: {resp.text[:200]}"
        )


class TestVersionParamIsTyped:
    def test_non_numeric_version_is_422_not_500(self, harness):
        """Component versions are integers; a non-numeric value must fail
        validation like teams/workflows, not 500 in a bare int() cast."""
        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": "hi", "stream": "false", "version": "not-a-number"},
        )
        assert resp.status_code == 422, (
            f"non-numeric version must fail validation like teams/workflows, got {resp.status_code}"
        )


class TestDebugLogOmitsMessageContent:
    def test_team_submit_does_not_log_raw_message(self, harness, benign_team_run):
        """Handler attached DIRECTLY to the agno loggers: they do not
        propagate to root, so caplog alone captures nothing and the test
        would pass vacuously."""
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: records.append(record)  # type: ignore[method-assign]
        import agno.utils.log as agno_log

        touched = []
        # The router's `logger` binding is whichever module-global object was
        # current at import; cover both concrete loggers.
        for logger_obj in (agno_log.agent_logger, agno_log.team_logger):
            old_level = logger_obj.level
            logger_obj.addHandler(handler)
            logger_obj.setLevel(logging.DEBUG)
            touched.append((logger_obj, old_level))
        try:
            resp = harness.client.post(
                "/teams/qa-team/runs",
                data={"message": "SECRET-PAYLOAD-42", "stream": "false"},
            )
        finally:
            for logger_obj, old_level in touched:
                logger_obj.removeHandler(handler)
                logger_obj.setLevel(old_level)
        assert resp.status_code == 200
        assert records, "the debug line must have been captured - otherwise this test proves nothing"
        offending = [r for r in records if "SECRET-PAYLOAD-42" in str(r.getMessage())]
        assert offending == [], "user message content must not appear in the log stream"
