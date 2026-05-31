import asyncio
from typing import Any, Dict, List

import pytest

from agno.tracing.exporter import DatabaseSpanExporter
from agno.tracing.schemas import Span


def _exporter() -> DatabaseSpanExporter:
    return DatabaseSpanExporter(db=object())  # type: ignore[arg-type]


def test_export_async_keeps_background_task_until_it_completes() -> None:
    async def run_test() -> None:
        exporter = _exporter()
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_export(spans_by_trace: Dict[str, List[Span]]) -> None:
            started.set()
            await release.wait()

        exporter._do_async_export = fake_export  # type: ignore[method-assign]

        exporter._export_async({"trace-id": []})

        assert len(exporter._background_tasks) == 1
        await asyncio.wait_for(started.wait(), timeout=1)
        assert len(exporter._background_tasks) == 1

        task = next(iter(exporter._background_tasks))
        release.set()
        await asyncio.wait_for(task, timeout=1)

        assert exporter._background_tasks == set()

    asyncio.run(run_test())


def test_export_async_observes_background_task_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run_test() -> None:
        exporter = _exporter()
        errors: List[str] = []

        async def failing_export(spans_by_trace: Dict[str, List[Span]]) -> None:
            raise RuntimeError("boom")

        exporter._do_async_export = failing_export  # type: ignore[method-assign]
        monkeypatch.setattr("agno.tracing.exporter.log_error", errors.append)

        exporter._export_async({"trace-id": []})
        task = next(iter(exporter._background_tasks))

        with pytest.raises(RuntimeError, match="boom"):
            await asyncio.wait_for(task, timeout=1)

        assert exporter._background_tasks == set()
        assert errors == ["Failed to export async traces: boom"]

    asyncio.run(run_test())


def test_export_async_runs_directly_without_running_loop() -> None:
    exporter = _exporter()
    calls: List[Any] = []

    async def fake_export(spans_by_trace: Dict[str, List[Span]]) -> None:
        calls.append(spans_by_trace)

    exporter._do_async_export = fake_export  # type: ignore[method-assign]

    exporter._export_async({"trace-id": []})

    assert calls == [{"trace-id": []}]
    assert exporter._background_tasks == set()
