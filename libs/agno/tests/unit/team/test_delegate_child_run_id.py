import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.models.response import ToolExecution
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team._default_tools import _get_delegate_task_function
from agno.tools.function import FunctionCall


def _build_delegate_function(async_mode: bool, members: Dict[str, MagicMock]):
    team = MagicMock()
    team.delegate_to_all_members = False
    team.respond_directly = False
    team.add_history_to_context = False
    team.add_team_history_to_members = False
    team.determine_input_for_members = True
    team.enable_agentic_knowledge_filters = False

    run_response = TeamRunOutput(
        run_id="team-run",
        tools=[
            ToolExecution(tool_call_id="tool-call-1", tool_name="delegate_task_to_member"),
            ToolExecution(tool_call_id="tool-call-2", tool_name="delegate_task_to_member"),
        ],
    )
    run_context = RunContext(
        run_id="team-run",
        session_id="session",
        session_state={},
    )
    session = MagicMock()
    session.session_id = "session"
    team_run_context: Dict[str, Any] = {}

    with (
        patch("agno.team._init._initialize_member"),
        patch(
            "agno.team._tools._find_member_by_id",
            side_effect=lambda _team, member_id, run_context: (0, members[member_id]),
        ),
        patch("agno.team._default_tools.add_interaction_to_team_run_context"),
        patch("agno.team._run._update_team_media"),
        patch("agno.team._run._member_run_for_storage", side_effect=lambda _team, _session, response: response),
        patch("agno.team._run._amember_run_for_storage", new_callable=AsyncMock),
    ):
        function = _get_delegate_task_function(
            team=team,
            run_response=run_response,
            run_context=run_context,
            session=session,
            team_run_context=team_run_context,
            async_mode=async_mode,
        )

    function._team = team
    function._run_context = run_context
    return function, run_response


def _member(member_id: str) -> MagicMock:
    member = MagicMock()
    member.id = member_id
    member.name = member_id
    member.store_media = True
    member.store_tool_messages = True
    member.store_history_messages = True
    member.add_history_to_context = False
    member.knowledge = None
    member.knowledge_filters = None
    member.run.return_value = RunOutput(run_id=f"member-run-{member_id}", content=f"{member_id} done")
    return member


def _consume_sync(function, call_id: str, member_id: str) -> None:
    call = FunctionCall(
        function=function,
        call_id=call_id,
        arguments={"member_id": member_id, "task": f"task for {member_id}"},
    )
    result = call.execute()
    assert result.status == "success"
    list(result.result)


def test_sync_delegate_calls_keep_their_tool_call_child_run_mapping():
    members = {"one": _member("one"), "two": _member("two")}
    function, run_response = _build_delegate_function(async_mode=False, members=members)

    _consume_sync(function, "tool-call-1", "one")
    _consume_sync(function, "tool-call-2", "two")

    assert {tool.tool_call_id: tool.child_run_id for tool in run_response.tools or []} == {
        "tool-call-1": "member-run-one",
        "tool-call-2": "member-run-two",
    }


@pytest.mark.asyncio
async def test_async_delegate_calls_keep_their_tool_call_child_run_mapping_out_of_order():
    members = {"one": _member("one"), "two": _member("two")}

    async def run_member(member_id: str, *args: Any, **kwargs: Any) -> RunOutput:
        if member_id == "one":
            await asyncio.sleep(0.01)
        return RunOutput(run_id=f"member-run-{member_id}", content=f"{member_id} done")

    for member_id, member in members.items():

        async def arun(*args: Any, _member_id=member_id, **kwargs: Any) -> RunOutput:
            return await run_member(_member_id)

        member.arun = AsyncMock(side_effect=arun)

    function, run_response = _build_delegate_function(async_mode=True, members=members)

    async def consume(call_id: str, member_id: str) -> None:
        call = FunctionCall(
            function=function,
            call_id=call_id,
            arguments={"member_id": member_id, "task": f"task for {member_id}"},
        )
        result = await call.aexecute()
        assert result.status == "success"
        async for _ in result.result:
            pass

    await asyncio.gather(
        consume("tool-call-1", "one"),
        consume("tool-call-2", "two"),
    )

    assert {tool.tool_call_id: tool.child_run_id for tool in run_response.tools or []} == {
        "tool-call-1": "member-run-one",
        "tool-call-2": "member-run-two",
    }
