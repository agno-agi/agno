"""Unit tests for the MCP run tools' result serialization and progress reporting.

The run tools return trimmed results by default: MCP tool results are injected into
the consuming model's context, so the transcript, system prompt, and metrics must not
leak into them. ``result_mode="full"`` is the opt-in escape hatch. Runs are driven as
streams so tool-call / step events surface as MCP progress notifications.
"""

import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.media import Image  # noqa: E402
from agno.models.message import Message  # noqa: E402
from agno.models.response import ToolExecution  # noqa: E402
from agno.os import AgentOS, MCPServerConfig  # noqa: E402
from agno.os.mcp import build_mcp_server  # noqa: E402
from agno.run.agent import RunErrorEvent, RunEvent, RunOutput, ToolCallStartedEvent  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.run.requirement import RunRequirement  # noqa: E402
from agno.run.workflow import (  # noqa: E402
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowRunOutput,
)
from agno.workflow.step import Step  # noqa: E402
from agno.workflow.workflow import Workflow  # noqa: E402

_PNG_BYTES = b"\x89PNG\r\n\x1a\n_fake_image_payload"


def _agent() -> Agent:
    return Agent(id="demo-agent", name="Demo Agent")


def _stub_arun_stream(component, *items):
    """Replace ``component.arun`` with an async generator yielding ``items`` in order."""

    async def fake_arun(message, **kwargs):
        for item in items:
            yield item

    component.arun = fake_arun  # type: ignore[method-assign]


@pytest.fixture(autouse=True)
def _resolve_by_identity(monkeypatch):
    """Resolve run tools to the in-memory (stubbed) component instance.

    Production ``_resolve_run_component`` deep-copies (create_fresh) and consults the DB
    registry, which would discard the ``.arun`` stub these tests set on the instance. The
    real resolution behaviour (create_fresh isolation, db/registry, factories) is covered
    by test_mcp_resolution.py.
    """

    async def _resolve(os, kind, component_id, *, user_id, session_id):
        pool = {"agents": os.agents, "teams": os.teams, "workflows": os.workflows}.get(kind) or []
        for component in pool:
            if getattr(component, "id", None) == component_id:
                return component
        singular = {"agents": "Agent", "teams": "Team", "workflows": "Workflow"}[kind]
        raise Exception(f"{singular} {component_id} not found")

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", _resolve)


def _full_run_output() -> RunOutput:
    """A run output carrying everything the trimmed mode must NOT ship to the client."""
    return RunOutput(
        run_id="run-1",
        session_id="sess-1",
        content="the answer",
        status=RunStatus.completed,
        messages=[
            Message(role="system", content="SECRET_SYSTEM_PROMPT"),
            Message(role="user", content="hi"),
            Message(role="assistant", content="the answer"),
        ],
    )


async def _call_run_agent(os: AgentOS, **kwargs):
    async with Client(build_mcp_server(os)) as client:
        return await client.call_tool("run_agent", {"agent_id": "demo-agent", "message": "hi"}, **kwargs)


# ==================== Trimmed mode (default) ====================


async def test_trimmed_result_carries_answer_and_ids_only():
    agent = _agent()
    _stub_arun_stream(agent, _full_run_output())
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    result = await _call_run_agent(os)

    assert result.content[0].text == "the answer"
    assert result.structured_content == {
        "run_id": "run-1",
        "session_id": "sess-1",
        "status": "COMPLETED",
    }


async def test_trimmed_result_does_not_leak_transcript_or_system_prompt():
    agent = _agent()
    _stub_arun_stream(agent, _full_run_output())
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    result = await _call_run_agent(os)

    serialized = str(result.content) + str(result.structured_content)
    assert "SECRET_SYSTEM_PROMPT" not in serialized
    assert "messages" not in (result.structured_content or {})


async def test_binary_media_becomes_image_content_block():
    """A run with raw image bytes serializes as an MCP image block instead of erroring."""
    run_output = _full_run_output()
    run_output.images = [Image(content=_PNG_BYTES, mime_type="image/png")]
    agent = _agent()
    _stub_arun_stream(agent, run_output)
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    result = await _call_run_agent(os)

    image_blocks = [b for b in result.content if getattr(b, "type", None) == "image"]
    assert len(image_blocks) == 1
    assert image_blocks[0].mimeType == "image/png"
    assert image_blocks[0].data  # base64 payload present


async def test_paused_run_reports_requirements():
    run_output = RunOutput(
        run_id="run-p",
        session_id="sess-p",
        status=RunStatus.paused,
        requirements=[RunRequirement(tool_execution=ToolExecution(tool_name="send_email", requires_confirmation=True))],
    )
    agent = _agent()
    _stub_arun_stream(agent, run_output)
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    result = await _call_run_agent(os)

    structured = result.structured_content or {}
    assert structured["status"] == "PAUSED"
    assert len(structured["requirements"]) == 1
    assert "paused" in result.content[0].text.lower()


# ==================== Full mode (escape hatch) ====================


async def test_full_mode_ships_complete_run_output():
    agent = _agent()
    _stub_arun_stream(agent, _full_run_output())
    os = AgentOS(
        agents=[agent],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(result_mode="full"),
    )

    result = await _call_run_agent(os)

    structured = result.structured_content or {}
    assert structured["run_id"] == "run-1"
    assert len(structured["messages"]) == 3  # full mode keeps the transcript, by choice
    assert result.content[0].text == "the answer"


async def test_full_mode_survives_binary_media():
    """Full mode must route through to_dict() so raw bytes cannot break serialization."""
    run_output = _full_run_output()
    run_output.images = [Image(content=_PNG_BYTES, mime_type="image/png")]
    agent = _agent()
    _stub_arun_stream(agent, run_output)
    os = AgentOS(
        agents=[agent],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(result_mode="full"),
    )

    result = await _call_run_agent(os)

    assert (result.structured_content or {})["run_id"] == "run-1"


# ==================== Progress notifications ====================


async def test_tool_call_events_are_forwarded_as_progress():
    agent = _agent()
    started_event = ToolCallStartedEvent(
        event=RunEvent.tool_call_started.value,
        tool=ToolExecution(tool_name="duckduckgo_search"),
    )
    _stub_arun_stream(agent, started_event, _full_run_output())
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    messages = []

    async def on_progress(progress, total, message):
        messages.append(message)

    result = await _call_run_agent(os, progress_handler=on_progress)

    assert result.content[0].text == "the answer"
    assert any("started" in (m or "") for m in messages)
    assert any("duckduckgo_search" in (m or "") for m in messages)


# ==================== Workflow runs ====================


async def test_workflow_result_built_from_completed_event():
    workflow = Workflow(id="demo-wf", name="Demo WF", steps=[Step(agent=_agent())])
    completed = WorkflowCompletedEvent(
        run_id="wf-run-1",
        session_id="wf-sess-1",
        content="workflow done",
        run_output=WorkflowRunOutput(
            run_id="wf-run-1",
            session_id="wf-sess-1",
            content="workflow done",
            status=RunStatus.completed,
        ),
    )
    _stub_arun_stream(workflow, completed)
    os = AgentOS(workflows=[workflow], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("run_workflow", {"workflow_id": "demo-wf", "message": "go"})

    assert result.content[0].text == "workflow done"
    structured = result.structured_content or {}
    assert structured["run_id"] == "wf-run-1"
    assert structured["status"] == "COMPLETED"


async def test_run_finishing_without_output_raises_tool_error():
    """A stream that ends without a final output surfaces as a tool error, not a hang."""
    agent = _agent()
    _stub_arun_stream(agent)  # yields nothing
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    result = await _call_run_agent(os, raise_on_error=False)
    assert result.is_error


# ==================== Error and pause propagation ====================


async def test_failed_run_surfaces_real_error_message():
    """The streaming error path yields only a RunErrorEvent; its message must reach the client."""
    agent = _agent()
    _stub_arun_stream(agent, RunErrorEvent(content="Incorrect API key provided"))
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    result = await _call_run_agent(os, raise_on_error=False)

    assert result.is_error
    assert "Incorrect API key provided" in result.content[0].text


async def test_paused_workflow_recovered_from_persisted_run():
    """Foreground workflow streams end WITHOUT a terminal event on HITL pause; the tool
    must fetch the persisted run so the client gets run_id + requirements to continue."""
    workflow = Workflow(id="demo-wf", name="Demo WF", steps=[Step(agent=_agent())])
    _stub_arun_stream(workflow, StepStartedEvent(run_id="wf-run-p", session_id="wf-sess-p", step_name="approve"))

    paused = WorkflowRunOutput(run_id="wf-run-p", session_id="wf-sess-p", content=None, status=RunStatus.paused)
    fetched = {}

    async def fake_aget_run_output(run_id, session_id=None, user_id=None):
        fetched["run_id"] = run_id
        fetched["session_id"] = session_id
        return paused

    workflow.aget_run_output = fake_aget_run_output  # type: ignore[method-assign]
    os = AgentOS(workflows=[workflow], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("run_workflow", {"workflow_id": "demo-wf", "message": "go"})

    assert fetched == {"run_id": "wf-run-p", "session_id": "wf-sess-p"}
    assert (result.structured_content or {})["status"] == "PAUSED"


async def test_nested_workflow_error_does_not_abort_outer_run():
    """A nested workflow's error event (nested_depth > 0) must not kill an outer run
    that recovers from it."""
    workflow = Workflow(id="demo-wf", name="Demo WF", steps=[Step(agent=_agent())])
    outer_output = WorkflowRunOutput(
        run_id="wf-outer", session_id="wf-sess", content="recovered", status=RunStatus.completed
    )
    _stub_arun_stream(
        workflow,
        WorkflowErrorEvent(run_id="wf-nested", error="nested boom", nested_depth=1),
        WorkflowCompletedEvent(run_id="wf-outer", session_id="wf-sess", content="recovered", run_output=outer_output),
    )
    os = AgentOS(workflows=[workflow], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("run_workflow", {"workflow_id": "demo-wf", "message": "go"})

    structured = result.structured_content or {}
    assert structured["run_id"] == "wf-outer"
    assert structured["status"] == "COMPLETED"


async def test_workflow_progress_is_strictly_increasing():
    """MCP requires progress to increase per notification, even when step indexes repeat
    (loops) or reset (nested steps)."""
    workflow = Workflow(id="demo-wf", name="Demo WF", steps=[Step(agent=_agent())])
    events = [
        StepStartedEvent(run_id="r", session_id="s", step_name="a", step_index=0),
        StepStartedEvent(run_id="r", session_id="s", step_name="a", step_index=0),  # loop iteration repeats index
        StepStartedEvent(run_id="r", session_id="s", step_name="b", step_index=1),
        WorkflowCompletedEvent(
            run_id="r",
            session_id="s",
            content="done",
            run_output=WorkflowRunOutput(run_id="r", session_id="s", content="done", status=RunStatus.completed),
        ),
    ]
    _stub_arun_stream(workflow, *events)
    os = AgentOS(workflows=[workflow], enable_mcp_server=True)

    values = []

    async def on_progress(progress, total, message):
        values.append(progress)

    async with Client(build_mcp_server(os)) as client:
        await client.call_tool(
            "run_workflow", {"workflow_id": "demo-wf", "message": "go"}, progress_handler=on_progress
        )

    assert values == sorted(values)
    assert len(values) == len(set(values)), f"progress values must strictly increase, got {values}"


async def test_paused_workflow_fallback_text_counts_step_requirements():
    """The paused fallback text must count workflow step_requirements, not just
    agent/team requirements."""
    from agno.os.mcp_results import build_run_tool_result
    from agno.workflow.types import StepRequirement

    paused = WorkflowRunOutput(run_id="r", session_id="s", content=None, status=RunStatus.paused)
    paused.step_requirements = [
        StepRequirement(step_id="step-1", step_name="approve", step_type="Step", requires_confirmation=True)
    ]

    result = build_run_tool_result(paused, "trimmed")

    text = result.content[0].text
    assert "1 requirement" in text
