"""An approved resumed run must retain completed exchanges on terminal error."""

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools import tool


class FailingAfterApproval(Model):
    def __init__(self):
        super().__init__(id="test", name="test", provider="test")
        self.calls = 0
        self.recover = False
        self.seen = []

    def invoke(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs):
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke_stream(self, messages, **kwargs):
        self.calls += 1
        self.seen.append([m.to_dict() for m in messages])
        if self.recover:
            yield ModelResponse(content="Recovered with prior results")
            return
        name = {1: "confirm_scope", 2: "record_effect"}.get(self.calls)
        if name:
            yield ModelResponse(
                tool_calls=[
                    {
                        "id": f"tool-{self.calls}",
                        "type": "function",
                        "function": {"name": name, "arguments": "{}"},
                    }
                ]
            )
            return
        yield ModelResponse(content="Partial final prose before transport failure")
        raise ModelProviderError(
            message="controlled incomplete chunked read",
            model_name="test",
            model_id="test",
        )

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


async def probe(level, background):
    effects = []

    @tool(requires_confirmation=True)
    def confirm_scope():
        return "accepted scope revision1"

    def record_effect():
        effects.append("written")
        return "durable file created"

    db = InMemoryDb()
    model = FailingAfterApproval()
    agent = Agent(
        id="test",
        model=model,
        db=db,
        tools=[confirm_scope, record_effect],
        checkpoint=level,
        telemetry=False,
        store_events=True,
        add_history_to_context=True,
    )
    agent.num_history_runs = None
    initial = [
        e
        async for e in agent.arun(
            "prepare",
            session_id="session",
            user_id="reviewer",
            stream=True,
            stream_events=True,
        )
    ]
    rid = initial[0].run_id
    r = agent.get_run_output(run_id=rid, session_id="session")
    assert str(r.status) == "PAUSED"
    r.requirements[0].confirm()
    async for _ in agent.acontinue_run(
        run_response=r,
        user_id="reviewer",
        stream=True,
        stream_events=True,
        background=background,
    ):
        pass
    stored = agent.get_run_output(run_id=rid, session_id="session")
    assert str(stored.status) == "ERROR"
    result = {
        "checkpoint": level,
        "background": background,
        "run_id": rid,
        "error_message_count": len(stored.messages or []),
        "stored_roles": [m.role for m in stored.messages or []],
        "tool_result_ids": [m.tool_call_id for m in stored.messages or [] if m.role == "tool"],
        "stored_content": stored.content,
        "tool_executions": [t.tool_call_id for t in stored.tools or []],
        "events": [],
        "check_index": stored.last_checkpoint_at_message_index,
    }
    model.recover = True
    recovered = [
        e
        async for e in agent.acontinue_run(
            run_id=rid,
            session_id="session",
            user_id="reviewer",
            stream=True,
            stream_events=True,
        )
    ]
    result["same_run"] = all(e.run_id == rid for e in recovered)
    result["recovered_status"] = str(agent.get_run_output(run_id=rid, session_id="session").status)
    result["recovery_model_messages"] = model.seen[-1]
    result["effects_count"] = len(effects)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("background", [False, True])
async def test_error_after_approved_scope_retains_completed_tools_and_resumes_once(
    background,
):
    result = await probe("runs", background)
    assert result["tool_result_ids"] == ["tool-1", "tool-2"]
    assert result["same_run"] is True
    assert result["recovered_status"] == "COMPLETED"
    assert result["effects_count"] == 1
    messages = result["recovery_model_messages"]
    assert [m.get("tool_call_id") for m in messages if m["role"] == "tool"] == [
        "tool-1",
        "tool-2",
    ]
    assert sum(m["role"] == "user" for m in messages) == 1
    # Partial transport text remains evidence, not an invented completed response.
    assert result["stored_content"] == "Partial final prose before transport failure"
    assert all(m.get("content") != result["stored_content"] for m in messages)
