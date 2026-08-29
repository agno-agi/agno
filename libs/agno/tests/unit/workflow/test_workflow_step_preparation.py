from agno.workflow.step import Step
from agno.workflow.workflow import Workflow


def test_prepare_steps_keeps_history_step_without_database():
    history_step = Step(name="history", executor=lambda: None, add_workflow_history=True)
    regular_step = Step(name="regular", executor=lambda: None)
    workflow = Workflow(steps=[history_step, regular_step])

    workflow._prepare_steps()

    assert workflow.steps == [history_step, regular_step]
