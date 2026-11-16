"""A RemoteAgent runs as a workflow step."""

import time
from unittest.mock import AsyncMock

import pytest

from agno.agent.remote import RemoteAgent
from agno.os.routers.agents.schema import AgentResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.workflow import Step, Workflow


@pytest.mark.asyncio
async def test_remote_agent_step_completes_and_receives_workflow_context():
    remote = RemoteAgent(base_url="http://remote:7777", agent_id="a1")
    remote._cached_agent_config = (AgentResponse(id="a1", name="a1"), time.time())
    run_agent = AsyncMock(side_effect=lambda **kwargs: RunOutput(run_id=kwargs["run_id"], content="remote ok"))
    remote.agentos_client.run_agent = run_agent  # type: ignore[method-assign]
    workflow = Workflow(
        name="remote-step",
        steps=[Step(name="s1", agent=remote, max_retries=0)],
        dependencies={"tier": "gold"},
        metadata={"source": "workflow"},
    )

    result = await workflow.arun("hi")

    assert result.status == RunStatus.completed
    assert result.content == "remote ok"
    sent = run_agent.call_args.kwargs
    assert "run_context" not in sent
    assert sent["dependencies"] == {"tier": "gold"}
    assert sent["metadata"] == {"source": "workflow"}
