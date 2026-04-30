from agno.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.team import Team


def test_delegate_task_passes_team_run_id_as_member_parent_run_id(monkeypatch):
    member = Agent(name="Member Agent")
    team = Team(name="Parent Team", members=[member])
    captured = {}

    def fake_run(self, **kwargs):
        captured["parent_run_id"] = kwargs.get("parent_run_id")
        return RunOutput(run_id="member-run", session_id=kwargs.get("session_id"), content="done")

    monkeypatch.setattr(Agent, "run", fake_run)

    delegate = team._get_delegate_task_function(
        session=TeamSession(session_id="team-session"),
        run_response=TeamRunOutput(run_id="team-run"),
        run_context=RunContext(run_id="team-run", session_id="team-session", session_state={}),
        team_run_context={},
    )

    response = list(delegate.entrypoint(member_id="member-agent", task="do the work"))

    assert captured["parent_run_id"] == "team-run"
    assert response == ["done"]
