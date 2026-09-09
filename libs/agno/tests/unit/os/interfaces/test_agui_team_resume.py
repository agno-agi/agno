"""Regression: AG-UI resume of a paused TEAM MEMBER run must resume the top-level TeamRunOutput,
not the member RunOutput that a member pause also persists (its missing team_id crashes core on
continue). Drives a real team.arun -> member pause -> persist -> resume_paused_run with a scripted
(no-network) model, so it reproduces the actual crash rather than a mock of it."""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.os.interfaces.agui.resume import resume_paused_run
from agno.run.base import RunContext, RunStatus
from agno.team import Team
from agno.tools import tool


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id) or ('content', text)."""

    def __init__(self, model_id: str, script: List[tuple]):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, tcid = turn
            r = ModelResponse(role="assistant")
            r.tool_calls = [{"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
            return r
        r = ModelResponse(content=turn[1], role="assistant")
        r.event = ModelResponseEvent.assistant_response.value
        return r

    def invoke(self, *a, **k):
        return self._next()

    async def ainvoke(self, *a, **k):
        return self._next()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


@tool(requires_confirmation=True)
def send_email(to: str, subject: str, body: str) -> str:
    return f"Email sent to {to}"


def _build_team(db: SqliteDb) -> Team:
    emailer = Agent(
        name="Emailer",
        id="emailer",
        model=_ScriptedModel(
            "m-emailer",
            [
                ("tool", "send_email", {"to": "a@example.com", "subject": "hi", "body": "x"}, "tc-send"),
                ("content", "Email sent."),
            ],
        ),
        tools=[send_email],
        db=db,
        telemetry=False,
        instructions="Use send_email.",
    )
    return Team(
        name="Comms Team",
        id="comms-team",
        model=_ScriptedModel(
            "m-leader",
            [
                ("tool", "delegate_task_to_member", {"member_id": "emailer", "task": "send it"}, "tc-deleg"),
                ("content", "All done."),
            ],
        ),
        members=[emailer],
        db=db,
        telemetry=False,
        instructions="Delegate to Emailer.",
    )


async def test_agui_resume_team_member_pause_resumes_team_run(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "team_hitl.db"))
    team = _build_team(db)
    session_id = "s-team"

    # Drive to a real member send_email pause.
    paused = False
    async for ev in team.arun("Email a@example.com", session_id=session_id, stream=True, stream_events=True):
        if type(ev).__name__ == "RunPausedEvent":
            paused = True
    assert paused, "expected a member send_email pause"

    # Resume through the AG-UI bridge with the confirmation ToolMessage.
    tm = AGUIToolMessage(id="m1", role="tool", content=json.dumps({"accepted": True}), tool_call_id="tc-send")
    gen = await resume_paused_run(
        entity=team,
        session_id=session_id,
        tool_messages=[tm],
        run_context=RunContext(run_id="new", session_id=session_id),
        run_kwargs={},
    )
    async for _ in gen:  # today: raises AttributeError('RunOutput'...team_id); after fix: completes
        pass

    # The TEAM run (not the member run) was resumed and completed.
    session = db.get_session(session_id=session_id, session_type="team")
    team_run = next(r for r in (session.runs or []) if type(r).__name__ == "TeamRunOutput")
    assert team_run.status == RunStatus.completed
