"""Generated media must cross container boundaries and survive persistence."""

import pytest

from agno.db.in_memory import InMemoryDb
from agno.media import Audio, File, Image, Video
from agno.workflow import Condition, Loop, Parallel, Router, Step, Steps, Workflow
from agno.workflow.types import HumanReview, StepInput, StepOutput

MEDIA_FIELDS = ("images", "videos", "audio", "files")
MODES = ("sync", "async", "stream", "async_stream")


def _media_ids(output):
    return {field: [item.id for item in getattr(output, field) or []] for field in MEDIA_FIELDS}


def _producer(name):
    count = 0

    def produce(step_input: StepInput) -> StepOutput:
        nonlocal count
        count += 1
        media_id = f"{name}-{count}"
        return StepOutput(
            content=media_id,
            images=[Image(id=media_id, url="https://example.com/image.png")],
            videos=[Video(id=media_id, url="https://example.com/video.mp4")],
            audio=[Audio(id=media_id, url="https://example.com/audio.wav")],
            files=[File(id=media_id, name=f"{media_id}.txt", content=b"report")],
        )

    return Step(name=name, executor=produce)


def _consume(step_input: StepInput) -> StepOutput:
    return StepOutput(content=_media_ids(step_input))


def _wrap(kind, children):
    if kind == "direct":
        return children
    if kind == "parallel":
        return [Parallel(*children, name="wrapped")]
    if kind == "steps":
        return [Steps(name="wrapped", steps=children)]
    if kind == "condition":
        return [Condition(name="wrapped", evaluator=True, steps=children)]
    if kind == "else_condition":
        return [Condition(name="wrapped", evaluator=False, steps=[], else_steps=children)]
    if kind == "loop":
        return [Loop(name="wrapped", steps=children, max_iterations=2)]
    if kind == "router":
        return [Router(name="wrapped", selector=lambda si: [child.name for child in children], choices=children)]
    if kind == "nested_workflow":
        return [Step(name="wrapped", workflow=Workflow(name="child", steps=children, telemetry=False))]
    if kind == "parallel_in_steps":
        return [Steps(name="outer", steps=[Parallel(*children, name="inner")])]
    if kind == "nested_containers":
        return [Steps(name="outer", steps=[Condition(name="inner", evaluator=True, steps=children)])]
    raise AssertionError(f"Unknown wrapper: {kind}")


async def _run(workflow, mode, paused=None):
    if mode == "sync":
        result = workflow.continue_run(paused) if paused is not None else workflow.run("start")
    elif mode == "async":
        result = await workflow.acontinue_run(paused) if paused is not None else await workflow.arun("start")
    elif mode == "stream":
        events = list(
            workflow.continue_run(paused, stream=True, stream_events=True)
            if paused is not None
            else workflow.run("start", stream=True, stream_events=True)
        )
        result = workflow.get_run(events[-1].run_id)
    else:
        iterator = (
            await workflow.acontinue_run(paused, stream=True, stream_events=True)
            if paused is not None
            else workflow.arun("start", stream=True, stream_events=True)
        )
        events = [event async for event in iterator]
        result = workflow.get_run(events[-1].run_id)
    assert result is not None
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "kind",
    [
        "direct",
        "parallel",
        "steps",
        "condition",
        "else_condition",
        "loop",
        "router",
        "nested_workflow",
        "nested_containers",
        "parallel_in_steps",
    ],
)
async def test_container_media_reaches_next_step_and_saved_run(kind, mode):
    workflow = Workflow(
        name="media",
        db=InMemoryDb(),
        telemetry=False,
        steps=_wrap(kind, [_producer("first"), _producer("second")]) + [Step(name="consume", executor=_consume)],
    )
    result = await _run(workflow, mode)
    expected_ids = ["first-1", "second-1"]
    if kind == "loop":
        expected_ids += ["first-2", "second-2"]
    expected = {field: expected_ids for field in MEDIA_FIELDS}
    # No recursive recounting: each artifact appears once even across multiple wrappers.
    assert result.content == expected
    assert _media_ids(result) == expected
    assert _media_ids(workflow.get_run(result.run_id)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_loop_review_exposes_container_media_to_next_step(mode):
    workflow = Workflow(
        name="reviewed-media",
        db=InMemoryDb(),
        telemetry=False,
        steps=[
            Loop(
                name="refine",
                steps=[_producer("version")],
                max_iterations=3,
                human_review=HumanReview(requires_iteration_review=True),
            ),
            Step(name="consume", executor=_consume),
        ],
    )
    paused = await _run(workflow, mode)
    assert paused.is_paused
    assert _media_ids(paused.step_results[-1]) == {field: ["version-1"] for field in MEDIA_FIELDS}
    paused.steps_requiring_output_review[0].confirm()
    result = await _run(workflow, mode, paused)
    expected = {field: ["version-1"] for field in MEDIA_FIELDS}
    assert result.content == expected
    assert _media_ids(result.step_results[0]) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_empty_container_media_remains_none(mode):
    workflow = Workflow(
        name="no-media",
        db=InMemoryDb(),
        telemetry=False,
        steps=[Steps(name="wrapped", steps=[Step(name="text", executor=lambda si: StepOutput(content="text"))])],
    )
    result = await _run(workflow, mode)
    output = result.step_results[0]
    assert all(getattr(output, field) is None for field in MEDIA_FIELDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind", ["parallel", "steps", "nested_containers"])
async def test_distinct_child_outputs_with_the_same_media_id_are_preserved(kind, mode):
    def produce(step_input: StepInput) -> StepOutput:
        return StepOutput(content="file", files=[File(id="same", name="report.txt", content=b"report")])

    workflow = Workflow(
        name="repeated-media",
        db=InMemoryDb(),
        telemetry=False,
        steps=_wrap(kind, [Step(name="first", executor=produce), Step(name="second", executor=produce)])
        + [Step(name="consume", executor=_consume)],
    )
    result = await _run(workflow, mode)
    # Match Parallel's existing concatenation semantics rather than deduplicating
    # separate outputs merely because their user-supplied media ids are equal.
    assert result.content["files"] == ["same", "same"]
    assert [file.id for file in result.files] == ["same", "same"]
