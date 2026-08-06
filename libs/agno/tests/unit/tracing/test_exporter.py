import inspect

from agno.tracing.exporter import DatabaseSpanExporter


def test_export_async_keeps_strong_reference_to_task():
    """Regression test: scheduled async export tasks must be strongly referenced.

    asyncio only keeps a weak reference to a task created with create_task, so a
    fire-and-forget task can be garbage-collected before it finishes, silently
    dropping traces. The exporter must retain the task (and release it on
    completion) instead of discarding the return value.
    """
    source = inspect.getsource(DatabaseSpanExporter._export_async)

    # The task reference must be captured, not thrown away.
    assert "_background_tasks" in source
    assert "add_done_callback" in source


def test_export_async_uses_get_running_loop():
    """Regression test: must not use the deprecated asyncio.get_event_loop().

    asyncio.get_event_loop() is deprecated since Python 3.10 when there is no
    running loop. The exporter should detect the running loop with
    get_running_loop() and fall back to asyncio.run() otherwise.
    """
    source = inspect.getsource(DatabaseSpanExporter._export_async)

    assert "get_event_loop" not in source
    assert "get_running_loop" in source
