from __future__ import annotations

from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run import RunStatus
from agno.team import Team
from agno.team.autonomy.models import TeamExecutionMode
from agno.team.autonomy.session_store import SESSION_STATE_JOBS_KEY


class SequenceModel(Model):
    def __init__(self, contents: List[str]):
        super().__init__(id="sequence-model", name="sequence-model", provider="test")
        self._contents = list(contents)

    def _next(self) -> str:
        if not self._contents:
            return ""
        return self._contents.pop(0)

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
        return ModelResponse(
            role="assistant",
            content=self._next(),
            tool_calls=[],
            tool_executions=None,
            event=ModelResponseEvent.assistant_response.value,
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
        return self.response(messages=messages)

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


def test_supervised_autonomy_pauses_and_resumes_with_approvals():
    plan_json = (
        '{"steps": ['
        '{"title": "Step A", "instructions": "Do A", "requires_approval": false},'
        '{"title": "Step B", "instructions": "Do B", "requires_approval": true}'
        "]}"
    )
    team_model = SequenceModel([plan_json, "A done", "B done", "FINAL"])
    member = Agent(name="Member", model=SequenceModel(["member"]))

    team = Team(
        members=[member],
        model=team_model,
        cache_session=True,
        telemetry=False,
    )

    # 1) Initial supervised run pauses for plan approval
    resp1 = team.run(
        "Do the thing",
        mode=TeamExecutionMode.SUPERVISED,
        session_id="session_1",
        stream=False,
    )
    assert resp1.status == RunStatus.paused
    assert resp1.metadata is not None and "job_id" in resp1.metadata
    job_id = resp1.metadata["job_id"]

    assert resp1.session_state is not None
    assert SESSION_STATE_JOBS_KEY in resp1.session_state
    assert job_id in resp1.session_state[SESSION_STATE_JOBS_KEY]

    # 2) Approve plan; Step A executes; job pauses before Step B
    resp2 = team.run(
        "resume",
        mode=TeamExecutionMode.SUPERVISED,
        session_id="session_1",
        job_id=job_id,
        resume=True,
        approval=True,
        stream=False,
    )
    assert resp2.status == RunStatus.paused
    assert resp2.content is not None and "Approval required" in str(resp2.content)

    # 3) Approve Step B; job completes with final synthesis
    resp3 = team.run(
        "resume",
        mode=TeamExecutionMode.SUPERVISED,
        session_id="session_1",
        job_id=job_id,
        resume=True,
        approval=True,
        stream=False,
    )
    assert resp3.status == RunStatus.completed
    assert resp3.content == "FINAL"
