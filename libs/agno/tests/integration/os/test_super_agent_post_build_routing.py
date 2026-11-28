"""Exercise Super Agent's routing after a published build and a draft build."""

import os
from uuid import uuid4

import pytest

from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from agno.registry import Registry
from agno.run.base import RunStatus
from agno.workflow import Step, StepInput, StepOutput, Workflow

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")


def make_manager(db, workflows=None):
    agent_os = AgentOS(
        db=db,
        workflows=workflows,
        registry=Registry(models=[OpenAIResponses()]),
        manager=OSManager(access_docs=False),
        telemetry=False,
    )
    return agent_os.manager


def test_named_workflow_runs_after_publishing_an_agent(shared_db):
    forecast_reference = uuid4().hex[:12]

    def forecast(step_input: StepInput) -> StepOutput:
        return StepOutput(content=f"Forecast reference {forecast_reference}")

    workflow = Workflow(id="forecast", name="Forecast", db=shared_db, steps=[Step(name="Forecast", executor=forecast)])
    manager = make_manager(shared_db, workflows=[workflow])
    build = manager.run(
        "Build and publish an agent with id meeting-notes that turns meeting notes into action items.",
        session_id="post-build",
        user_id="alice",
    )
    notes = shared_db.get_component("meeting-notes")
    assert notes and notes["current_version"], build.content
    assert not shared_db.get_runs(workflow_id="forecast")

    reply = manager.run(
        "Run the Forecast workflow on these meeting notes and give me its reference. "
        "Meeting notes: Lee expects 20 orders on Friday.",
        session_id="post-build",
        user_id="alice",
    )
    runs = shared_db.get_runs(workflow_id="forecast")
    assert len(runs) == 1 and runs[0].status == RunStatus.completed, reply.content
    assert forecast_reference in str(reply.content)
    assert not shared_db.get_runs(agent_id="meeting-notes")


def test_sample_input_does_not_dispatch_a_draft(shared_db):
    manager = make_manager(shared_db)
    build = manager.run(
        "Build an agent with id meeting-notes that turns meeting notes into action items. "
        "Save it as a draft for me to review before publishing.",
        session_id="draft-review",
        user_id="alice",
    )
    notes = shared_db.get_component("meeting-notes")
    assert notes and notes["current_version"] is None, build.content

    reply = manager.run(
        "Meeting notes: Lee will order the paper by Friday.", session_id="draft-review", user_id="alice"
    )
    calls = {tool.tool_name for tool in reply.tools or []}
    assert calls.isdisjoint({"run_agent", "start_background_run"}), calls
    assert not shared_db.get_runs(agent_id="meeting-notes")
    assert shared_db.get_component("meeting-notes")["current_version"] is None
    assert reply.status == RunStatus.completed and "draft" in str(reply.content).lower(), reply.content
