import json
from copy import deepcopy
from typing import Any, AsyncIterator, Iterator, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent import Agent
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.os.routers.teams.schema import TeamResponse
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutput
from agno.run.approval import _apply_approval_to_tools
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team import Team
from agno.team._default_tools import _format_member_response_content
from agno.tools.function import FunctionCall

NO_RESPONSE = "No response from the member agent."


class _DelegatingModel(Model):
    """Call delegation once and optionally produce a final leader response."""

    def __init__(self, final_content: Optional[str] = None):
        super().__init__(id="delegating", name="delegating", provider="test")
        self.final_content = final_content
        self.invoke_count = 0
        self.invocations: list[list[Any]] = []

    def __deepcopy__(self, memo: dict) -> "_DelegatingModel":
        return self

    def _next(self) -> ModelResponse:
        self.invoke_count += 1
        if self.invoke_count == 1:
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {
                    "id": "delegate-call",
                    "type": "function",
                    "function": {
                        "name": "delegate_task_to_member",
                        "arguments": json.dumps({"member_id": "worker", "task": "Use your tool"}),
                    },
                }
            ]
        elif self.invoke_count == 2 and self.final_content is not None:
            response = ModelResponse(
                content=self.final_content,
                role="assistant",
                event=ModelResponseEvent.assistant_response.value,
            )
        else:
            raise AssertionError("model invoked beyond its script")
        response.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._record_messages(args, kwargs)
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._record_messages(args, kwargs)
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        self._record_messages(args, kwargs)
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        self._record_messages(args, kwargs)
        yield self._next()

    def _record_messages(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        messages = kwargs.get("messages")
        if messages is None and args:
            messages = args[0]
        self.invocations.append(deepcopy(messages or []))

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def _tool_only_response(content: Optional[str]) -> RunOutput:
    return RunOutput(
        run_id="member-run",
        agent_id="worker",
        agent_name="Worker",
        content=content,
        tools=[
            ToolExecution(tool_name="first", result="RAW"),
            ToolExecution(tool_name="empty", result=None),
            ToolExecution(tool_name="second", result="SECOND"),
        ],
    )


def _delegate_function(
    *,
    response: RunOutput,
    fallback_setting: Optional[bool],
    delegate_to_all_members: bool,
    async_mode: bool,
) -> tuple[Team, TeamRunOutput, Any]:
    member = Agent(id="worker", name="Worker")
    member.run = MagicMock(return_value=response)  # type: ignore[method-assign]
    member.arun = AsyncMock(return_value=response)  # type: ignore[method-assign]

    team_kwargs: dict[str, Any] = {
        "members": [member],
        "delegate_to_all_members": delegate_to_all_members,
    }
    if fallback_setting is not None:
        team_kwargs["use_member_tool_results_as_fallback"] = fallback_setting

    team = Team(**team_kwargs)
    team_run_response = TeamRunOutput(run_id="team-run")
    function = team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=team_run_response,
        run_context=RunContext(session_state={}, run_id="team-run", session_id="test-session"),
        team_run_context={},
        async_mode=async_mode,
    )
    assert function.entrypoint is not None
    return team, team_run_response, function


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "  \n", None])
@pytest.mark.parametrize("fallback_setting", [None, True, False])
@pytest.mark.parametrize("delegate_to_all_members", [False, True])
@pytest.mark.parametrize("async_mode", [False, True])
async def test_tool_result_fallback_across_delegation_paths(
    content: Optional[str],
    fallback_setting: Optional[bool],
    delegate_to_all_members: bool,
    async_mode: bool,
):
    response = _tool_only_response(content)
    _, team_run_response, function = _delegate_function(
        response=response,
        fallback_setting=fallback_setting,
        delegate_to_all_members=delegate_to_all_members,
        async_mode=async_mode,
    )

    kwargs = {"task": "Use your tool"}
    if not delegate_to_all_members:
        kwargs["member_id"] = "worker"

    assert function.entrypoint is not None
    if async_mode:
        output = [item async for item in function.entrypoint(**kwargs)]
    else:
        output = list(function.entrypoint(**kwargs))

    if fallback_setting is False:
        expected = f"Agent Worker: {NO_RESPONSE}" if delegate_to_all_members else NO_RESPONSE
        assert output == [expected]
    elif delegate_to_all_members:
        assert output == ["Agent Worker: RAW,SECOND"]
    else:
        assert output == ["RAW,SECOND"]

    assert team_run_response.member_responses
    assert team_run_response.member_responses[0].tools
    assert team_run_response.member_responses[0].tools[0].result == "RAW"


@pytest.mark.parametrize("use_fallback", [True, False])
def test_non_empty_member_content_wins_over_tool_results(use_fallback: bool):
    response = _tool_only_response("Member answer")

    assert _format_member_response_content(response, use_tool_results_as_fallback=use_fallback) == "Member answer"


@pytest.mark.parametrize("content", ["", " \n", None])
@pytest.mark.parametrize("use_fallback", [True, False])
@pytest.mark.parametrize("tool_result", [None, "", " \n"])
def test_no_usable_content_returns_diagnostic(content: Optional[str], use_fallback: bool, tool_result: Optional[str]):
    response = RunOutput(
        content=content,
        tools=[ToolExecution(tool_name="empty", result=tool_result)],
    )

    assert _format_member_response_content(response, use_tool_results_as_fallback=use_fallback) == NO_RESPONSE


@pytest.mark.parametrize(
    ("tool_result", "expected"),
    [
        (0, "0"),
        (False, "False"),
        ({"answer": 42}, "{'answer': 42}"),
        (["alpha", {"beta": 2}], "['alpha', {'beta': 2}]"),
    ],
)
def test_approval_results_are_stringified(tool_result: Any, expected: str):
    tool = ToolExecution(
        tool_name="external",
        approval_type="required",
        external_execution_required=True,
    )
    _apply_approval_to_tools([tool], "approved", {"result": tool_result})
    response = RunOutput(content="", tools=[tool])

    assert _format_member_response_content(response, use_tool_results_as_fallback=True) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("delegate_to_all_members", [False, True])
@pytest.mark.parametrize("async_mode", [False, True])
async def test_leader_tool_message_receives_diagnostic(
    delegate_to_all_members: bool,
    async_mode: bool,
):
    response = RunOutput(content="", tools=[ToolExecution(tool_name="raw", result="SECRET_RAW")])
    _, _, function = _delegate_function(
        response=response,
        fallback_setting=False,
        delegate_to_all_members=delegate_to_all_members,
        async_mode=async_mode,
    )
    arguments = {"task": "Use your tool"}
    if not delegate_to_all_members:
        arguments["member_id"] = "worker"

    function_call = FunctionCall(function=function, arguments=arguments, call_id="delegate-call")
    function_call_results = []
    model = _DelegatingModel()

    if async_mode:
        async for _ in model.arun_function_calls([function_call], function_call_results):
            pass
    else:
        list(model.run_function_call(function_call, function_call_results))

    expected = f"Agent Worker: {NO_RESPONSE}" if delegate_to_all_members else NO_RESPONSE
    assert len(function_call_results) == 1
    assert function_call_results[0].content == expected
    assert function_call_results[0].content != ""
    assert "SECRET_RAW" not in function_call_results[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("use_fallback", [False, True])
async def test_respond_directly_applies_member_tool_fallback_end_to_end(
    async_mode: bool,
    use_fallback: bool,
):
    response = RunOutput(
        run_id="member-run",
        agent_id="worker",
        agent_name="Worker",
        content="",
        tools=[ToolExecution(tool_name="raw", result="SECRET_RAW")],
        status=RunStatus.completed,
    )
    member = Agent(id="worker", name="Worker")
    member.run = MagicMock(return_value=response)  # type: ignore[method-assign]
    member.arun = AsyncMock(return_value=response)  # type: ignore[method-assign]
    model = _DelegatingModel()
    team = Team(
        model=model,
        members=[member],
        respond_directly=True,
        use_member_tool_results_as_fallback=use_fallback,
        telemetry=False,
    )

    if async_mode:
        result = await team.arun("Use your tool")
    else:
        result = team.run("Use your tool")

    expected = "SECRET_RAW" if use_fallback else NO_RESPONSE
    assert isinstance(result, TeamRunOutput)
    assert result.content == expected
    assert result.status == RunStatus.completed
    tool_messages = [message for message in result.messages or [] if message.role == "tool"]
    assert tool_messages
    assert tool_messages[-1].content == expected
    assert tool_messages[-1].stop_after_tool_call is True
    assert response.tools and response.tools[0].result == "SECRET_RAW"
    assert model.invoke_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("use_fallback", [False, True])
async def test_leader_receives_filtered_delegate_tool_message_end_to_end(
    async_mode: bool,
    use_fallback: bool,
):
    response = RunOutput(
        run_id="member-run",
        agent_id="worker",
        agent_name="Worker",
        content="",
        tools=[ToolExecution(tool_name="raw", result="SECRET_RAW")],
        status=RunStatus.completed,
    )
    member = Agent(id="worker", name="Worker")
    member.run = MagicMock(return_value=response)  # type: ignore[method-assign]
    member.arun = AsyncMock(return_value=response)  # type: ignore[method-assign]
    model = _DelegatingModel(final_content="LEADER")
    team = Team(
        model=model,
        members=[member],
        use_member_tool_results_as_fallback=use_fallback,
        telemetry=False,
    )

    if async_mode:
        result = await team.arun("Use your tool")
    else:
        result = team.run("Use your tool")

    assert isinstance(result, TeamRunOutput)
    assert result.content == "LEADER"
    assert result.status == RunStatus.completed
    assert model.invoke_count == 2
    delegate_messages = [
        message
        for message in model.invocations[1]
        if message.role == "tool" and message.tool_call_id == "delegate-call"
    ]
    assert len(delegate_messages) == 1
    expected = "SECRET_RAW" if use_fallback else NO_RESPONSE
    assert delegate_messages[0].content == expected
    assert response.tools and response.tools[0].result == "SECRET_RAW"


def test_fallback_setting_serialization_and_deep_copy():
    default_team = Team(id="default-team", members=[])
    assert default_team.use_member_tool_results_as_fallback is True
    assert "use_member_tool_results_as_fallback" not in default_team.to_dict()
    assert Team.from_dict(default_team.to_dict()).use_member_tool_results_as_fallback is True

    team = Team(id="configured-team", members=[], use_member_tool_results_as_fallback=False)
    config = team.to_dict()

    assert config["use_member_tool_results_as_fallback"] is False
    assert Team.from_dict(config).use_member_tool_results_as_fallback is False
    assert team.deep_copy().use_member_tool_results_as_fallback is False


def test_nested_teams_keep_their_own_fallback_setting():
    default_child = Team(id="default-child", members=[])
    disabled_parent = Team(
        id="disabled-parent",
        members=[default_child],
        use_member_tool_results_as_fallback=False,
    )
    disabled_parent._initialize_member(default_child)
    assert default_child.use_member_tool_results_as_fallback is True

    disabled_child = Team(id="disabled-child", members=[], use_member_tool_results_as_fallback=False)
    default_parent = Team(id="default-parent", members=[disabled_child])
    default_parent._initialize_member(disabled_child)
    assert disabled_child.use_member_tool_results_as_fallback is False


@pytest.mark.asyncio
async def test_agent_os_team_response_exposes_non_default_fallback_setting():
    default_response = await TeamResponse.from_team(Team(id="default-team", members=[]))
    configured_response = await TeamResponse.from_team(
        Team(id="configured-team", members=[], use_member_tool_results_as_fallback=False)
    )

    assert not default_response.response_settings or (
        "use_member_tool_results_as_fallback" not in default_response.response_settings
    )
    assert configured_response.response_settings
    assert configured_response.response_settings["use_member_tool_results_as_fallback"] is False
