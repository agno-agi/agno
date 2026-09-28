"""Memory evaluations must release tracing after failed or cancelled work."""

import asyncio
import tracemalloc
from pathlib import Path

import pytest

from agno.eval.performance import PerformanceEval


@pytest.fixture(autouse=True)
def cleanup_tracing():
    assert not tracemalloc.is_tracing()
    yield
    tracemalloc.stop()


def evaluation_for(func):
    return PerformanceEval(
        func=func,
        num_iterations=1,
        warmup_runs=0,
        measure_runtime=False,
        show_spinner=False,
        telemetry=False,
    )


@pytest.mark.parametrize("growth_tracking", [False, True])
def test_failed_memory_evaluation_stops_tracing_and_can_run_again(tmp_path: Path, growth_tracking: bool):
    input_file = tmp_path / "input.txt"
    evaluation = evaluation_for(input_file.read_bytes)

    with pytest.raises(FileNotFoundError):
        evaluation.run(memory_growth_tracking=growth_tracking)

    assert not tracemalloc.is_tracing()
    input_file.write_bytes(b"recovered" * 1024)
    result = evaluation.run(memory_growth_tracking=growth_tracking)
    assert 1 == len(result.memory_usages)
    assert result.memory_usages[0] >= 0
    assert not tracemalloc.is_tracing()


@pytest.mark.asyncio
@pytest.mark.parametrize("growth_tracking", [False, True])
async def test_failed_async_memory_evaluation_stops_tracing_and_can_run_again(tmp_path: Path, growth_tracking: bool):
    input_file = tmp_path / "input.txt"

    async def read_file():
        await asyncio.sleep(0)
        return input_file.read_bytes()

    evaluation = evaluation_for(read_file)
    with pytest.raises(FileNotFoundError):
        await evaluation.arun(memory_growth_tracking=growth_tracking)

    assert not tracemalloc.is_tracing()
    input_file.write_bytes(b"recovered" * 1024)
    result = await evaluation.arun(memory_growth_tracking=growth_tracking)
    assert 1 == len(result.memory_usages)
    assert result.memory_usages[0] >= 0
    assert not tracemalloc.is_tracing()


@pytest.mark.asyncio
@pytest.mark.parametrize("growth_tracking", [False, True])
async def test_cancelled_memory_evaluation_stops_tracing_and_can_run_again(growth_tracking: bool):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def work():
        entered.set()
        await release.wait()
        return bytearray(8192)

    evaluation = evaluation_for(work)
    task = asyncio.create_task(evaluation.arun(memory_growth_tracking=growth_tracking))
    await asyncio.wait_for(entered.wait(), timeout=5)
    assert tracemalloc.is_tracing()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not tracemalloc.is_tracing()
    release.set()
    result = await evaluation.arun(memory_growth_tracking=growth_tracking)
    assert 1 == len(result.memory_usages)
    assert result.memory_usages[0] >= 0
    assert not tracemalloc.is_tracing()


@pytest.mark.parametrize("growth_tracking", [False, True])
def test_base_exception_propagates_after_tracing_cleanup(growth_tracking: bool):
    error = KeyboardInterrupt()

    def interrupt():
        raise error

    with pytest.raises(KeyboardInterrupt) as raised:
        evaluation_for(interrupt).run(memory_growth_tracking=growth_tracking)

    assert error is raised.value
    assert not tracemalloc.is_tracing()
