"""The verification loop through AgentOS itself: continue and cancel of an unverified run
through the ordinary REST doors, with no runner and no special route."""

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.run.cancel import cleanup_run, is_cancelled, register_run
from agno.team import Team
from agno.verifiers import VerificationConfig

from .conftest import ScriptedModel, _text


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "os.db"))


@pytest.fixture
def client(db):
    """An AgentOS serving a verified agent and team whose check never passes."""

    def not_good_enough(run_output):
        return "not good enough"

    member = Agent(id="member", name="Member", model=ScriptedModel([_text("member ok")]))
    agent = Agent(
        id="verified-agent",
        name="Verified Agent",
        model=ScriptedModel([_text("claimed done")]),
        db=db,
        verifiers=[not_good_enough],
        verification=VerificationConfig(max_attempts=2),
    )
    team = Team(
        id="verified-team",
        name="Verified Team",
        members=[member],
        model=ScriptedModel([_text("claimed done")]),
        db=db,
        verifiers=[not_good_enough],
        verification=VerificationConfig(max_attempts=2),
    )
    with TestClient(AgentOS(agents=[agent], teams=[team], telemetry=False).get_app()) as test_client:
        yield test_client


def _unverified_run(client, kind: str, session_id: str) -> str:
    response = client.post(
        f"/{kind}s/verified-{kind}/runs",
        data={"message": "do the work", "stream": "false", "session_id": session_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "UNVERIFIED"
    return response.json()["run_id"]


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_continue_of_an_unverified_run_stays_in_place(client, kind):
    session_id = f"e2e-{kind}"
    run_id = _unverified_run(client, kind, session_id)

    # The run continues in place under the same run id; the check still fails.
    continued = client.post(
        f"/{kind}s/verified-{kind}/runs/{run_id}/continue",
        data={"session_id": session_id, "stream": "false", "input": "try again"},
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["run_id"] == run_id
    assert continued.json()["status"] == "UNVERIFIED"

    listed = client.get(f"/{kind}s/verified-{kind}/runs", params={"session_id": session_id})
    assert listed.status_code == 200
    (row,) = [r for r in listed.json() if r["run_id"] == run_id]
    assert row["verification"]["status"] == "unverified"
    assert row["verification"]["attempts"][0]["verdicts"][0]["report"] == "not good enough"


@pytest.mark.parametrize("cancel_session", ["same", "mismatched", "missing"])
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_cancel_of_an_unverified_run_records_nothing_and_the_continue_is_not_cancelled(client, kind, cancel_session):
    session_id = f"e2e-cancel-{kind}-{cancel_session}"
    run_id = _unverified_run(client, kind, session_id)
    params = {"same": {"session_id": session_id}, "mismatched": {"session_id": "another-session"}, "missing": {}}

    cancelled = client.post(f"/{kind}s/verified-{kind}/runs/{run_id}/cancel", params=params[cancel_session])
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json() == {}
    assert not is_cancelled(run_id)

    continued = client.post(
        f"/{kind}s/verified-{kind}/runs/{run_id}/continue",
        data={"session_id": session_id, "stream": "false", "input": "try again", "fork": "false"},
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["run_id"] == run_id
    assert continued.json()["status"] == "UNVERIFIED"

    # A continue still executing is registered, and its cancel is recorded
    register_run(run_id)
    try:
        assert (
            client.post(f"/{kind}s/verified-{kind}/runs/{run_id}/cancel", params=params[cancel_session]).status_code
            == 200
        )
        assert is_cancelled(run_id)
    finally:
        cleanup_run(run_id)
