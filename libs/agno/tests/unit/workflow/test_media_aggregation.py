"""Unit tests for media (files) propagation through workflow step containers.

Covers:
- Parallel._aggregate_results aggregating files from member step outputs
- Steps/Loop/Condition/Router _update_step_input_from_outputs chaining files
  into the next StepInput (images/videos/audio already propagate; files must too)
"""

from agno.media import File
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput


def _file(name: str) -> File:
    return File(name=name, content=b"payload")


def _output(step_name: str, files=None, images=None) -> StepOutput:
    return StepOutput(step_name=step_name, content=f"done {step_name}", files=files, images=images)


def _input(files=None) -> StepInput:
    return StepInput(input="start", files=files)


class TestParallelAggregatesFiles:
    """Parallel._aggregate_results must carry member files like images/videos/audio."""

    def test_single_result_files_are_propagated(self):
        parallel = Parallel(name="p")
        member_files = [_file("report.pdf")]

        result = parallel._aggregate_results([_output("step1", files=member_files)])

        assert result.files == member_files

    def test_multiple_results_files_are_aggregated(self):
        parallel = Parallel(name="p")
        first_files = [_file("a.csv")]
        second_files = [_file("b.csv"), _file("c.csv")]

        result = parallel._aggregate_results(
            [
                _output("step1", files=first_files),
                _output("step2", files=second_files),
            ]
        )

        assert result.files == first_files + second_files

    def test_no_files_stays_none(self):
        parallel = Parallel(name="p")

        result = parallel._aggregate_results([_output("step1"), _output("step2")])

        assert result.files is None


class TestContainersChainFiles:
    """Container _update_step_input_from_outputs must chain files into the next StepInput."""

    def _assert_chained(self, container, step_input, step_outputs):
        updated = container._update_step_input_from_outputs(step_input, step_outputs)

        assert updated.files is not None
        assert _file("carried.txt").name in [f.name for f in updated.files]

    def test_steps_chain_files(self):
        steps = Steps(name="s", steps=[Step(name="inner", executor=lambda si: StepOutput(content="x"))])
        carried = [_file("carried.txt")]

        self._assert_chained(steps, _input(), _output("step1", files=carried))

    def test_loop_chain_files(self):
        loop = Loop(name="l", steps=[Step(name="inner", executor=lambda si: StepOutput(content="x"))])
        carried = [_file("carried.txt")]

        self._assert_chained(loop, _input(), _output("step1", files=carried))

    def test_condition_chain_files(self):
        condition = Condition(
            name="c",
            evaluator=True,
            steps=[Step(name="inner", executor=lambda si: StepOutput(content="x"))],
        )
        carried = [_file("carried.txt")]

        self._assert_chained(condition, _input(), _output("step1", files=carried))

    def test_router_chain_files(self):
        router = Router(
            name="r",
            selector=lambda si: "inner",
            choices=[Step(name="inner", executor=lambda si: StepOutput(content="x"))],
        )
        carried = [_file("carried.txt")]

        self._assert_chained(router, _input(), _output("step1", files=carried))

    def test_existing_input_files_are_preserved(self):
        steps = Steps(name="s", steps=[Step(name="inner", executor=lambda si: StepOutput(content="x"))])
        existing = [_file("existing.txt")]
        produced = [_file("produced.txt")]

        updated = steps._update_step_input_from_outputs(_input(files=existing), _output("step1", files=produced))

        assert [f.name for f in updated.files] == ["existing.txt", "produced.txt"]
