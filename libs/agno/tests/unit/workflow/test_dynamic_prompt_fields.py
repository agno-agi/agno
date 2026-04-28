import pytest

from agno.run import RunContext
from agno.session.workflow import WorkflowSession
from agno.workflow.workflow import Workflow


def test_dynamic_workflow_prompt_fields_sync():
    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={"tenant": "acme"},
        metadata={"user_id": "user-1"},
    )
    workflow = Workflow(
        name=lambda run_context: f"{run_context.session_state['tenant']} workflow",
        description=lambda run_context: f"Description for {run_context.metadata['user_id']}",
    )
    session = WorkflowSession(session_id="session-1")

    dependencies = workflow._get_workflow_agent_dependencies(session=session, run_context=run_context)
    workflow_context = dependencies["workflow_context"]

    assert "Workflow Name: acme workflow" in workflow_context
    assert "Workflow Description: Description for user-1" in workflow_context
    assert "No previous workflow runs in this session." in workflow_context


@pytest.mark.asyncio
async def test_dynamic_workflow_prompt_fields_async():
    async def name_fn(run_context):
        return f"{run_context.session_state['tenant']} workflow"

    async def description_fn(run_context):
        return f"Description for {run_context.metadata['user_id']}"

    run_context = RunContext(
        run_id="run-1",
        session_id="session-1",
        session_state={"tenant": "acme"},
        metadata={"user_id": "user-1"},
    )
    workflow = Workflow(
        name=name_fn,
        description=description_fn,
    )
    session = WorkflowSession(session_id="session-1")

    dependencies = await workflow._aget_workflow_agent_dependencies(session=session, run_context=run_context)
    workflow_context = dependencies["workflow_context"]

    assert "Workflow Name: acme workflow" in workflow_context
    assert "Workflow Description: Description for user-1" in workflow_context
    assert "No previous workflow runs in this session." in workflow_context


def test_dynamic_workflow_prompt_fields_validate_string_type():
    run_context = RunContext(run_id="run-1", session_id="session-1")
    workflow = Workflow(
        description=lambda: ["not", "a", "string"],
    )
    session = WorkflowSession(session_id="session-1")

    with pytest.raises(Exception, match="description must resolve to a string"):
        workflow._get_workflow_agent_dependencies(session=session, run_context=run_context)
