"""Unit tests for DatabaseSpanExporter async task retention."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.tracing.exporter import DatabaseSpanExporter


@pytest.fixture
def async_db():
    """Create a mock async database."""
    from agno.db.base import AsyncBaseDb

    db = MagicMock(spec=AsyncBaseDb)
    db.upsert_trace = AsyncMock(return_value=None)
    db.create_spans = AsyncMock(return_value=None)
    return db


@pytest.fixture
def exporter(async_db):
    return DatabaseSpanExporter(db=async_db)


def test_pending_tasks_set_initialized(exporter):
    """Exporter should initialize with an empty pending tasks set."""
    assert hasattr(exporter, "_pending_tasks")
    assert isinstance(exporter._pending_tasks, set)
    assert len(exporter._pending_tasks) == 0


@pytest.mark.asyncio
async def test_export_async_retains_task_reference(exporter):
    """Tasks created during async export should be strongly referenced."""
    mock_spans_by_trace = {"trace-1": [MagicMock()]}

    exporter._do_async_export = AsyncMock()
    exporter._export_async(mock_spans_by_trace)

    assert len(exporter._pending_tasks) == 1

    # Let the task complete
    await asyncio.sleep(0.05)
    # After completion, the done callback should have removed it
    assert len(exporter._pending_tasks) == 0


@pytest.mark.asyncio
async def test_export_async_cleans_up_after_completion(exporter):
    """Completed tasks should be automatically removed from _pending_tasks."""
    mock_spans = {"trace-1": [MagicMock()]}

    exporter._do_async_export = AsyncMock()

    exporter._export_async(mock_spans)
    assert len(exporter._pending_tasks) == 1

    # Wait for task to finish
    task = next(iter(exporter._pending_tasks))
    await task

    assert len(exporter._pending_tasks) == 0


def test_export_async_falls_back_to_asyncio_run_outside_loop(async_db):
    """When no event loop is running, should fall back to asyncio.run()."""
    exporter = DatabaseSpanExporter(db=async_db)
    mock_spans = {"trace-1": [MagicMock()]}

    exporter._do_async_export = AsyncMock()
    # Outside any running loop, this should use asyncio.run()
    exporter._export_async(mock_spans)

    exporter._do_async_export.assert_called_once_with(mock_spans)
    assert len(exporter._pending_tasks) == 0
