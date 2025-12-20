from __future__ import annotations

from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.agent import Agent
from agno.models.message import Message
from agno.models.response import ModelResponse, ToolExecution
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.messages import RunMessages
from agno.run.requirement import RunRequirement
from agno.session.agent import AgentSession


def test_run_requirement_reject_accepts_note_and_sets_confirmation_note() -> None:
    tool_execution = ToolExecution(
        tool_call_id="call_123",
        tool_name="get_the_weather",
        tool_args={"city": "Tokyo"},
        requires_confirmation=True,
    )

    requirement = RunRequirement(tool_execution=tool_execution)
    requirement.reject("No, use the other tool")

    assert requirement.confirmation is False
    assert requirement.confirmation_note == "No, use the other tool"
    assert requirement.tool_execution is not None
    assert requirement.tool_execution.confirmed is False
    assert requirement.tool_execution.confirmation_note == "No, use the other tool"


def test_continue_run_populates_requirements_on_pause() -> None:
    class RecordingModel:
        last_run_response: Optional[RunOutput] = None
        assistant_message_role: str = "assistant"

        def response(
            self,
            *,
            messages: List[Message],
            response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
            tools: Optional[list[Any]] = None,
            tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
            tool_call_limit: Optional[int] = None,
            run_response: Optional[RunOutput] = None,
            send_media_to_model: bool = True,
            compression_manager: Optional[Any] = None,
        ) -> ModelResponse:
            self.last_run_response = run_response

            paused_tool = ToolExecution(
                tool_call_id="call_pause_1",
                tool_name="sensitive_tool",
                tool_args={"arg": "value"},
                requires_confirmation=True,
            )

            if run_response is not None:
                if run_response.requirements is None:
                    run_response.requirements = []
                run_response.requirements.append(RunRequirement(tool_execution=paused_tool))

            return ModelResponse(tool_executions=[paused_tool])

    model = RecordingModel()
    agent = Agent(model="openai:gpt-4o-mini")
    agent.model = model  # type: ignore[assignment]

    run_response = RunOutput(run_id="run_123", session_id="session_123")
    run_messages = RunMessages(messages=[Message(role="user", content="continue")])
    run_context = RunContext(
        run_id="run_123", session_id="session_123", user_id=None, session_state={}, dependencies={}
    )
    session = AgentSession(session_id="session_123", runs=[run_response])

    result = agent._continue_run(  # type: ignore[attr-defined]
        run_response=run_response,
        run_messages=run_messages,
        run_context=run_context,
        session=session,
        tools=[],
        user_id=None,
    )

    assert model.last_run_response is result
    assert result.is_paused is True
    assert result.requirements is not None
    assert len(result.active_requirements) == 1
    assert result.active_requirements[0].needs_confirmation is True


async def test_acontinue_run_populates_requirements_on_pause() -> None:
    class RecordingModel:
        last_run_response: Optional[RunOutput] = None
        assistant_message_role: str = "assistant"

        def to_dict(self) -> Dict[str, Any]:
            return {"id": "recording-model"}

        async def aresponse(
            self,
            *,
            messages: List[Message],
            response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
            tools: Optional[list[Any]] = None,
            tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
            tool_call_limit: Optional[int] = None,
            run_response: Optional[RunOutput] = None,
            send_media_to_model: bool = True,
            compression_manager: Optional[Any] = None,
        ) -> ModelResponse:
            self.last_run_response = run_response

            paused_tool = ToolExecution(
                tool_call_id="call_pause_1",
                tool_name="sensitive_tool",
                tool_args={"arg": "value"},
                requires_confirmation=True,
            )

            if run_response is not None:
                if run_response.requirements is None:
                    run_response.requirements = []
                run_response.requirements.append(RunRequirement(tool_execution=paused_tool))

            return ModelResponse(tool_executions=[paused_tool])

    model = RecordingModel()
    agent = Agent(model="openai:gpt-4o-mini")
    agent.model = model  # type: ignore[assignment]

    async def _aget_tools_stub(**_: Any) -> list[Any]:
        return []

    async def _noop_async(**_: Any) -> None:
        return None

    agent.aget_tools = _aget_tools_stub  # type: ignore[assignment]
    agent._ahandle_tool_call_updates = _noop_async  # type: ignore[assignment]

    run_response = RunOutput(
        run_id="run_123", session_id="session_123", messages=[Message(role="user", content="continue")]
    )
    run_context = RunContext(run_id="run_123", session_id="session_123", user_id=None, session_state={}, dependencies=None)

    result = await agent._acontinue_run(  # type: ignore[attr-defined]
        session_id="session_123",
        run_context=run_context,
        run_response=run_response,
        user_id=None,
    )

    assert model.last_run_response is result
    assert result.is_paused is True
    assert result.requirements is not None
    assert len(result.active_requirements) == 1
    assert result.active_requirements[0].needs_confirmation is True
