"""Regression tests: files must survive workflow pause + continue_run.

finalize_workflow_completion copies images/videos/audio from ContinueExecutionState
to the workflow run response but omitted files, even though the state tracks
output_files from post-pause steps (and restores pre-pause step files from
step_results). Files produced around a pause were therefore dropped from the
completed run response while images/videos/audio were kept.
"""

from pathlib import Path

from agno.db.sqlite import SqliteDb
from agno.media import File, Image
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, StepInput, StepOutput, WorkflowExecutionInput
from agno.workflow.utils.hitl import ContinueExecutionState, finalize_workflow_completion
from agno.workflow.workflow import Workflow


def _pre_pause_step(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="pre-pause result",
        files=[File(url="https://example.com/pre-pause.txt")],
    )


def _pause_step(step_input: StepInput) -> StepOutput:
    return StepOutput(content="paused step result")


def _post_pause_step(step_input: StepInput) -> StepOutput:
    return StepOutput(
        content="post-pause result",
        files=[File(url="https://example.com/post-pause.txt")],
        images=[Image(url="https://example.com/post-pause.png")],
    )


def _make_workflow(db_file: Path) -> Workflow:
    return Workflow(
        name="resume_files_workflow",
        db=SqliteDb(db_file=str(db_file)),
        steps=[
            Step(name="pre_pause_step", executor=_pre_pause_step),
            Step(name="pause_step", executor=_pause_step, human_review=HumanReview(requires_confirmation=True)),
            Step(name="post_pause_step", executor=_post_pause_step),
        ],
    )


def _file_urls(files):
    return [f.url for f in (files or [])]


class TestFinalizeWorkflowCompletionFiles:
    """Direct tests of finalize_workflow_completion media copying."""

    def test_finalize_copies_files_from_state(self):
        workflow_run_response = WorkflowRunOutput()
        execution_input = WorkflowExecutionInput(input="test")
        state = ContinueExecutionState(workflow_run_response, execution_input)

        post_pause_file = File(url="https://example.com/post-pause.txt")
        state.add_step_output(
            "post_pause_step",
            StepOutput(content="post-pause result", files=[post_pause_file]),
        )

        finalize_workflow_completion(workflow_run_response, state)

        assert workflow_run_response.status == RunStatus.completed
        assert workflow_run_response.files is not None
        assert workflow_run_response.files == state.output_files
        assert post_pause_file in workflow_run_response.files

    def test_finalize_preserves_pre_existing_files(self):
        pre_pause_file = File(url="https://example.com/pre-pause.txt")
        workflow_run_response = WorkflowRunOutput(
            step_results=[StepOutput(step_name="pre_pause_step", content="pre-pause result", files=[pre_pause_file])]
        )
        execution_input = WorkflowExecutionInput(input="test")
        state = ContinueExecutionState(workflow_run_response, execution_input)

        post_pause_file = File(url="https://example.com/post-pause.txt")
        state.add_step_output(
            "post_pause_step",
            StepOutput(content="post-pause result", files=[post_pause_file]),
        )

        finalize_workflow_completion(workflow_run_response, state)

        assert workflow_run_response.files is not None
        assert pre_pause_file in workflow_run_response.files
        assert post_pause_file in workflow_run_response.files


class TestContinueRunFiles:
    """Behavioral tests: pause a real workflow, continue it, check files on the response."""

    def test_continue_run_returns_files_from_pre_and_post_pause_steps(self, tmp_path: Path):
        workflow = _make_workflow(tmp_path / "resume_files_sync.db")

        run_output = workflow.run("test input")
        assert run_output.is_paused
        assert run_output.steps_requiring_confirmation

        run_output.steps_requiring_confirmation[0].confirm()
        run_output = workflow.continue_run(run_output)

        assert run_output.status == RunStatus.completed
        # Images from post-pause steps are already propagated; files must be too.
        assert "https://example.com/post-pause.png" in [img.url for img in (run_output.images or [])]
        urls = _file_urls(run_output.files)
        assert "https://example.com/pre-pause.txt" in urls
        assert "https://example.com/post-pause.txt" in urls

    async def test_acontinue_run_returns_files_from_pre_and_post_pause_steps(self, tmp_path: Path):
        workflow = _make_workflow(tmp_path / "resume_files_async.db")

        run_output = await workflow.arun("test input")
        assert run_output.is_paused
        assert run_output.steps_requiring_confirmation

        run_output.steps_requiring_confirmation[0].confirm()
        run_output = await workflow.acontinue_run(run_output)

        assert run_output.status == RunStatus.completed
        assert "https://example.com/post-pause.png" in [img.url for img in (run_output.images or [])]
        urls = _file_urls(run_output.files)
        assert "https://example.com/pre-pause.txt" in urls
        assert "https://example.com/post-pause.txt" in urls
