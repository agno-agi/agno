"""Rejected step outputs must not contribute media when a workflow resumes."""

from typing import Optional

import pytest

from agno.db.in_memory import InMemoryDb
from agno.media import Audio, File, Image, Video
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.workflow import Step, Workflow
from agno.workflow.types import HumanReview, StepInput, StepOutput, WorkflowExecutionInput
from agno.workflow.utils.hitl import ContinueExecutionState


async def _run_or_continue(
    workflow: Workflow, mode: str, paused: Optional[WorkflowRunOutput] = None, input_media=None
) -> WorkflowRunOutput:
    input_media = input_media or {}
    if mode == "sync":
        return workflow.continue_run(paused) if paused else workflow.run("start", **input_media)
    if mode == "async":
        return await workflow.acontinue_run(paused) if paused else await workflow.arun("start", **input_media)
    if mode == "stream":
        events = list(
            workflow.continue_run(paused, stream=True, stream_events=True)
            if paused
            else workflow.run("start", stream=True, stream_events=True, **input_media)
        )
    else:
        stream = (
            await workflow.acontinue_run(paused, stream=True, stream_events=True)
            if paused
            else workflow.arun("start", stream=True, stream_events=True, **input_media)
        )
        events = [event async for event in stream]
    run = workflow.get_run(events[-1].run_id)
    assert run is not None
    return run


def _media_output(label: str) -> StepOutput:
    # IDs can be reused across outputs; discarding a step must not remove a
    # different step's accepted media just because it has the same ID.
    return StepOutput(
        content=label,
        images=[Image(id="shared-image", url=f"https://example.com/{label}.png")],
        videos=[Video(id="shared-video", url=f"https://example.com/{label}.mp4")],
        audio=[Audio(id="shared-audio", url=f"https://example.com/{label}.mp3")],
        files=[File(id="shared-file", url=f"https://example.com/{label}.txt")],
    )


def _media_urls(value):
    return {
        field: [item.url for item in getattr(value, field) or []] for field in ("images", "videos", "audio", "files")
    }


@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
@pytest.mark.parametrize("on_reject", ["skip", "retry"])
@pytest.mark.parametrize("with_input_media", [False, True])
async def test_rejected_step_media_is_discarded_on_resume(mode: str, on_reject: str, with_input_media: bool):
    reviewed_inputs = []
    downstream_inputs = []
    original_input = _media_output("input") if with_input_media else StepOutput(content="start")
    original_urls = _media_urls(original_input)
    input_media = {field: getattr(original_input, field) for field in original_urls}

    def before(step_input: StepInput) -> StepOutput:
        return _media_output("before")

    def reviewed(step_input: StepInput) -> StepOutput:
        reviewed_inputs.append(_media_urls(step_input))
        return _media_output("rejected" if len(reviewed_inputs) == 1 else "accepted")

    def after(step_input: StepInput) -> StepOutput:
        downstream_inputs.append(_media_urls(step_input))
        return _media_output("after")

    workflow = Workflow(
        db=InMemoryDb(),
        telemetry=False,
        steps=[
            Step(name="before", executor=before),
            Step(
                name="reviewed",
                executor=reviewed,
                human_review=HumanReview(requires_output_review=True, on_reject=on_reject),
            ),
            Step(name="after", executor=after),
        ],
    )

    run = await _run_or_continue(workflow, mode, input_media=input_media)
    assert run.is_paused
    run.steps_requiring_output_review[0].reject()
    run = await _run_or_continue(workflow, mode, run)
    if on_reject == "retry":
        assert run.is_paused
        run.steps_requiring_output_review[0].confirm()
        run = await _run_or_continue(workflow, mode, run)

    assert run.status == RunStatus.completed
    assert _media_urls(original_input) == original_urls
    before_urls = {field: original_urls[field] + urls for field, urls in _media_urls(_media_output("before")).items()}
    assert reviewed_inputs == [before_urls] * (2 if on_reject == "retry" else 1)
    expected_downstream = {
        field: urls + (_media_urls(_media_output("accepted"))[field] if on_reject == "retry" else [])
        for field, urls in before_urls.items()
    }
    assert downstream_inputs == [expected_downstream]
    assert [step.content for step in run.step_results] == (
        ["before", "accepted", "after"] if on_reject == "retry" else ["before", "after"]
    )
    for field in ("images", "videos", "audio", "files"):
        assert _media_urls(run)[field] == expected_downstream[field] + _media_urls(_media_output("after"))[field]


@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
async def test_repeated_reviews_do_not_duplicate_input_or_step_media(mode: str):
    received = []
    original_input = _media_output("input")
    original_urls = _media_urls(original_input)
    input_media = {field: getattr(original_input, field) for field in original_urls}

    def first(step_input: StepInput) -> StepOutput:
        return _media_output("first")

    def second(step_input: StepInput) -> StepOutput:
        return _media_output("second")

    def consume(step_input: StepInput) -> StepOutput:
        received.append(_media_urls(step_input))
        return StepOutput(content="complete")

    workflow = Workflow(
        db=InMemoryDb(),
        telemetry=False,
        steps=[
            Step(name="first", executor=first, human_review=HumanReview(requires_output_review=True)),
            Step(name="second", executor=second, human_review=HumanReview(requires_output_review=True)),
            Step(name="consume", executor=consume),
        ],
    )
    run = await _run_or_continue(workflow, mode, input_media=input_media)
    for step_name in ("first", "second"):
        assert run.is_paused
        assert run.paused_step_name == step_name
        run.steps_requiring_output_review[0].confirm()
        run = await _run_or_continue(workflow, mode, run)

    assert run.status == RunStatus.completed
    assert _media_urls(original_input) == original_urls
    assert received == [
        {
            field: urls + _media_urls(_media_output("first"))[field] + _media_urls(_media_output("second"))[field]
            for field, urls in original_urls.items()
        }
    ]
    assert _media_urls(run) == received[0]


@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
async def test_accepted_file_survives_confirmation_gate(mode: str):
    original_files = [File(url="https://example.com/input.txt")]

    def produce(step_input: StepInput) -> StepOutput:
        return StepOutput(content="accepted", files=[File(url="https://example.com/accepted.txt")])

    def confirmed(step_input: StepInput) -> StepOutput:
        return StepOutput(content="complete")

    workflow = Workflow(
        db=InMemoryDb(),
        telemetry=False,
        steps=[
            Step(name="produce", executor=produce),
            Step(name="gate", executor=confirmed, human_review=HumanReview(requires_confirmation=True)),
        ],
    )
    run = await _run_or_continue(workflow, mode, input_media={"files": original_files})
    assert run.is_paused
    run.step_requirements[-1].confirm()
    run = await _run_or_continue(workflow, mode, run)

    assert run.status == RunStatus.completed
    assert [file.url for file in original_files] == ["https://example.com/input.txt"]
    assert [file.url for file in run.files] == ["https://example.com/input.txt", "https://example.com/accepted.txt"]


def test_continuation_restores_media_without_mutating_execution_input():
    original_input = _media_output("input")
    original_urls = _media_urls(original_input)
    execution_input = WorkflowExecutionInput(
        input="start", **{field: getattr(original_input, field) for field in original_urls}
    )
    run = WorkflowRunOutput(step_results=[_media_output("before")])
    state = ContinueExecutionState(run, execution_input)
    state.add_step_output("after", _media_output("after"))

    assert _media_urls(execution_input) == original_urls
    for field, urls in original_urls.items():
        assert [item.url for item in getattr(state, f"shared_{field}")] == (
            urls + _media_urls(_media_output("before"))[field] + _media_urls(_media_output("after"))[field]
        )
