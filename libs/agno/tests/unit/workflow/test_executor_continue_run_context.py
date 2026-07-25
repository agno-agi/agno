from agno.db.in_memory import InMemoryDb
from agno.models.response import ToolExecution
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


class _PausingAgent:
    store_media = True
    store_tool_messages = True
    store_history_messages = True

    id = "pausing-agent"
    agent_id = id
    name = "Pausing Agent"

    def __init__(self):
        self.continue_contexts = []

    def run(self, **kwargs):
        tool = ToolExecution(
            tool_call_id="confirm-1",
            tool_name="confirm_artifact",
            tool_args={},
            requires_confirmation=True,
        )
        return RunOutput(
            run_id=kwargs["run_id"],
            agent_id=self.agent_id,
            agent_name=self.name,
            session_id=kwargs.get("session_id"),
            status=RunStatus.paused,
            tools=[tool],
            requirements=[RunRequirement(tool_execution=tool)],
            session_state=kwargs.get("session_state"),
        )

    async def arun(self, **kwargs):
        return self.run(**kwargs)

    def continue_run(self, *, run_response, run_context=None, **kwargs):
        self.continue_contexts.append(run_context)
        assert isinstance(run_context, RunContext)
        assert run_context.session_state == {"artifact": {"id": "artifact-1"}}
        assert all(requirement.is_resolved() for requirement in run_response.requirements)
        return RunOutput(
            run_id=run_response.run_id,
            agent_id=self.agent_id,
            agent_name=self.name,
            session_id=run_response.session_id,
            status=RunStatus.completed,
            requirements=run_response.requirements,
            session_state=run_response.session_state,
        )

    async def acontinue_run(self, *, run_response, run_context=None, **kwargs):
        return self.continue_run(
            run_response=run_response,
            run_context=run_context,
            **kwargs,
        )


def _finish(step_input: StepInput) -> StepOutput:
    return StepOutput(content="finished")


def _workflow(agent: _PausingAgent) -> Workflow:
    return Workflow(
        name="executor-context",
        db=InMemoryDb(),
        telemetry=False,
        steps=[
            Step(name="pause", agent=agent),
            Step(name="finish", executor=_finish),
        ],
    )


def _confirm_requirement(run_output: RunOutput) -> None:
    requirement = run_output.step_requirements[-1].executor_requirements[0]
    if isinstance(requirement, dict):
        requirement["confirmation"] = True
        requirement["tool_execution"]["confirmed"] = True
    else:
        requirement.confirm()


def test_sync_executor_continue_restores_persisted_session_state():
    agent = _PausingAgent()
    workflow = _workflow(agent)
    paused = workflow.run(
        input="start",
        session_id="session-1",
        session_state={"artifact": {"id": "artifact-1"}},
    )
    _confirm_requirement(paused)

    completed = workflow.continue_run(paused)

    assert completed.status == RunStatus.completed
    assert len(agent.continue_contexts) == 1


async def test_async_executor_continue_restores_persisted_session_state():
    agent = _PausingAgent()
    workflow = _workflow(agent)
    paused = await workflow.arun(
        input="start",
        session_id="session-1",
        session_state={"artifact": {"id": "artifact-1"}},
    )
    _confirm_requirement(paused)

    completed = await workflow.acontinue_run(paused)

    assert completed.status == RunStatus.completed
    assert len(agent.continue_contexts) == 1
