"""A team leader's run identity reaches a member agent's Studio tools.

The template's Chief is a Team whose member (Agent Builder) holds
StudioTools. When a user talks to Chief, everything the builder creates
must be owned by that user. The delegation path threads
``member_agent.run(user_id=..., session_id=...)``
(``team/_default_tools.py``), the member run builds a ``RunContext`` from
it, and the framework injects that context into the member's tools.

This is the mock-model unit version of the live check this behavior
was built against: explicit user -> the tool
sees it and the write is owned; no user anywhere -> the write is unowned.
"""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.openai import OpenAIResponses
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.registry import Registry
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id) or ('content', text).

    Same double as test_paused_member_persistence.py; kept local so the two
    suites stay independent.
    """

    def __init__(self, model_id: str, script: List[tuple]):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0

    def __deepcopy__(self, memo: dict) -> "_ScriptedModel":
        # Members are deep-copied per delegation; the script cursor must be
        # shared or the copy replays turn one forever.
        return self

    def _next(self) -> ModelResponse:
        from agno.metrics import MessageMetrics

        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, tcid = turn
            r = ModelResponse(role="assistant")
            r.tool_calls = [{"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
        else:
            r = ModelResponse(content=turn[1], role="assistant")
            r.event = ModelResponseEvent.assistant_response.value
        r.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        return r

    def invoke(self, *a: Any, **k: Any):
        return self._next()

    async def ainvoke(self, *a: Any, **k: Any):
        return self._next()

    def invoke_stream(self, *a: Any, **k: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a: Any, **k: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **k: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="member-identity-db", db_file=str(tmp_path / "member_identity.db"))


def _build_team(db, agent_name: str) -> Team:
    registry = Registry(
        name="Member Identity Registry",
        tools=[CalculatorTools()],
        models=[OpenAIResponses(id="gpt-5.5")],
        dbs=[db],
    )
    member_model = _ScriptedModel(
        "member-double",
        [
            ("tool", "create_agent", {"name": agent_name, "instructions": "Say hi."}, "call-m1"),
            ("content", "created"),
        ],
    )
    leader_model = _ScriptedModel(
        "leader-double",
        [
            ("tool", "delegate_task_to_member", {"member_id": "mini-builder", "task": "Create the agent."}, "call-l1"),
            ("content", "done"),
        ],
    )
    builder = Agent(
        id="mini-builder",
        name="Mini Builder",
        model=member_model,
        tools=[StudioTools(registry=registry, db=db)],
        instructions="Create what you are asked to create.",
        telemetry=False,
    )
    return Team(
        id="mini-chief",
        name="Mini Chief",
        model=leader_model,
        members=[builder],
        instructions="Delegate to Mini Builder.",
        telemetry=False,
    )


def test_team_user_id_owns_the_members_studio_write(db):
    team = _build_team(db, "Built By Chief")
    result = team.run("Build me an agent.", user_id="alice-7", session_id="sess-t")
    assert result is not None
    row = db.get_component("built-by-chief")
    assert row is not None, "the member's Studio create did not land"
    assert row["user_id"] == "alice-7"
    stamp = (row.get("metadata") or {}).get("studio") or {}
    assert stamp.get("created_by") == "alice-7"


def test_team_run_without_user_creates_unowned(db):
    team = _build_team(db, "Ownerless Build")
    team.run("Build me an agent.", session_id="sess-u")
    row = db.get_component("ownerless-build")
    assert row is not None
    assert row["user_id"] is None
