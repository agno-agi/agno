import asyncio
from typing import Any, Dict, List

import pytest

from agno.tracing.exporter import DatabaseSpanExporter


def test_export_async_runs_without_running_loop():
    exporter = DatabaseSpanExporter(db=object())  # type: ignore[arg-type]
    exported: List[Dict[str, List[Any]]] = []

    async def fake_export(spans_by_trace):
        exported.append(spans_by_trace)

    exporter._do_async_export = fake_export  # type: ignore[method-assign]

    spans_by_trace: Dict[str, List[Any]] = {"trace-id": []}
    exporter._export_async(spans_by_trace)

    assert exported == [spans_by_trace]
    assert exporter._pending_tasks == set()


@pytest.mark.asyncio
async def test_export_async_keeps_running_loop_task_until_done():
    exporter = DatabaseSpanExporter(db=object())  # type: ignore[arg-type]
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_export(_spans_by_trace):
        started.set()
        await release.wait()

    exporter._do_async_export = fake_export  # type: ignore[method-assign]

    exporter._export_async({"trace-id": []})
    await started.wait()

    assert len(exporter._pending_tasks) == 1
    task = next(iter(exporter._pending_tasks))
    assert not task.done()

    release.set()
    await task

    assert exporter._pending_tasks == set()
