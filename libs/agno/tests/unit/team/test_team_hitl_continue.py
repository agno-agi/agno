from __future__ import annotations

from typing import Any, Dict, List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run import RunStatus
from agno.run.requirement import RunRequirement
from agno.team import Team
from agno.team.autonomy.models import TeamExecutionMode
from agno.tools.function import Function


class ConfirmToolModel(Model):
    """A minimal model that pauses once on a tool call, then completes after tool result is present."""

    def __init__(self, *, final_content: str):
        super().__init__(id="confirm-tool-model", name="confirm-tool-model", provider="test")
        self._final_content = final_content

    def response(  # type: ignore[override]
        self,
        messages: List[Message],
        response_format: Optional[Any] = None,
        tools: Optional[Any] = None,
        tool_choice: Optional[Any] = None,
        tool_call_limit: Optional[int] = None,
        run_response: Optional[Any] = None,
        send_media_to_model: bool = True,
        compression_manager: Optional[Any] = None,
    ) -> ModelResponse:
        # If a tool result message exists, return final content.
        if any(m.role == self.tool_message_role for m in messages):
            messages.append(Message(role=self.assistant_message_role, content=self._final_content))
            return ModelResponse(
                role=self.assistant_message_role,
                content=self._final_content,
                tool_calls=[],
                tool_executions=None,
                event=ModelResponseEvent.assistant_response.value,
            )

        # Otherwise, pause on a tool call that requires confirmation.
        tool_call_id = "call_1"
        tool_calls = [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": "do_thing", "arguments": "{}"},
            }
        ]
        messages.append(Message(role=self.assistant_message_role, content="", tool_calls=tool_calls))

        tool_execution = ToolExecution(
            tool_call_id=tool_call_id,
            tool_name="do_thing",
            tool_args={},
            requires_confirmation=True,
        )
        if run_response is not None:
            if getattr(run_response, "requirements", None) is None:
                run_response.requirements = []
            run_response.requirements.append(RunRequirement(tool_execution=tool_execution))

        return ModelResponse(
            role=self.assistant_message_role,
            content="",
            tool_calls=tool_calls,
            tool_executions=[tool_execution],
            event=ModelResponseEvent.tool_call_paused.value,
        )

    async def aresponse(  # type: ignore[override]
        self,
        messages: List[Message],
        response_format: Optional[Any] = None,
        tools: Optional[Any] = None,
        tool_choice: Optional[Any] = None,
        tool_call_limit: Optional[int] = None,
        run_response: Optional[Any] = None,
        send_media_to_model: bool = True,
        compression_manager: Optional[Any] = None,
    ) -> ModelResponse:
        return self.response(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            tool_call_limit=tool_call_limit,
            run_response=run_response,
            send_media_to_model=send_media_to_model,
            compression_manager=compression_manager,
        )

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs) -> Dict[str, Any]:
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self.response(messages=kwargs.get("messages") or [])

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return await self.aresponse(messages=kwargs.get("messages") or [])

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield await self.ainvoke(*args, **kwargs)
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return ModelResponse(role="assistant", content="", tool_calls=[])

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse(role="assistant", content="", tool_calls=[])


class AutonomyToolPauseModel(ConfirmToolModel):
    def __init__(self):
        super().__init__(final_content="STEP DONE")

    def response(  # type: ignore[override]
        self,
        messages: List[Message],
        response_format: Optional[Any] = None,
        tools: Optional[Any] = None,
        tool_choice: Optional[Any] = None,
        tool_call_limit: Optional[int] = None,
        run_response: Optional[Any] = None,
        send_media_to_model: bool = True,
        compression_manager: Optional[Any] = None,
    ) -> ModelResponse:
        # Planning + synthesis calls use tools=None in the autonomy runner.
        if tools is None:
            system = next((m for m in messages if m.role == "system"), None)
            system_content = str(system.content) if system and system.content is not None else ""
            if "project planner" in system_content:
                plan_json = '{"steps":[{"title":"Step 1","instructions":"Do it","requires_approval":false}]}'
                return ModelResponse(
                    role=self.assistant_message_role,
                    content=plan_json,
                    tool_calls=[],
                    tool_executions=None,
                    event=ModelResponseEvent.assistant_response.value,
                )
            if "Synthesize a final answer" in system_content:
                return ModelResponse(
                    role=self.assistant_message_role,
                    content="FINAL",
                    tool_calls=[],
                    tool_executions=None,
                    event=ModelResponseEvent.assistant_response.value,
                )

        return super().response(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            tool_call_limit=tool_call_limit,
            run_response=run_response,
            send_media_to_model=send_media_to_model,
            compression_manager=compression_manager,
        )


def test_team_run_pauses_and_continue_run_completes_for_confirmed_tool():
    def do_thing() -> str:
        return "TOOL_OK"

    tool = Function.from_callable(do_thing, name="do_thing")
    tool.requires_confirmation = True

    team = Team(
        members=[],
        model=ConfirmToolModel(final_content="DONE"),
        tools=[tool],
        cache_session=True,
        telemetry=False,
    )

    paused = team.run("Do it", session_id="session_1", stream=False)
    assert paused.status == RunStatus.paused
    assert paused.requirements is not None and len(paused.requirements) == 1

    req = paused.requirements[0]
    assert req.needs_confirmation is True
    req.confirm()

    resumed = team.continue_run(run_id=paused.run_id, requirements=[req], session_id="session_1", stream=False)
    assert resumed.status == RunStatus.completed
    assert resumed.content == "DONE"
    assert resumed.tools is not None
    assert any(t.tool_name == "do_thing" and t.result == "TOOL_OK" for t in resumed.tools)


def test_autonomous_job_pauses_on_tool_confirmation_and_resumes_to_completion():
    def do_thing() -> str:
        return "TOOL_OK"

    tool = Function.from_callable(do_thing, name="do_thing")
    tool.requires_confirmation = True

    team = Team(
        members=[],
        model=AutonomyToolPauseModel(),
        tools=[tool],
        cache_session=True,
        telemetry=False,
    )

    resp1 = team.run("Goal", mode=TeamExecutionMode.AUTONOMOUS, session_id="session_1", stream=False)
    assert resp1.status == RunStatus.paused
    assert resp1.metadata is not None and "job_id" in resp1.metadata
    job_id = resp1.metadata["job_id"]

    resp2 = team.run(
        "resume",
        mode=TeamExecutionMode.AUTONOMOUS,
        session_id="session_1",
        job_id=job_id,
        resume=True,
        approval=True,
        stream=False,
    )
    assert resp2.status == RunStatus.completed
    assert resp2.content == "FINAL"
