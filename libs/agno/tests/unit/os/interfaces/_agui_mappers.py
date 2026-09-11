"""Drive a chunk sequence through the AG-UI mappers.

stream.py keeps the sync and async mappers as near-duplicate implementations and the
served HTTP route uses the async one, so a mapping test is worth running against both.
Every stream driven through `validated` is also checked against the framing rules in
`_agui_stream_rules`, so no test can assert its own two or three events while emitting a
sequence that breaks the run, the step spans, a message or a tool call around it.
"""

import asyncio

from agno.os.interfaces.agui.stream import (
    async_stream_agno_response_as_agui_events,
    stream_agno_response_as_agui_events,
)

from ._agui_stream_rules import assert_valid_agui_stream


def drive_sync_mapper(chunks):
    return list(stream_agno_response_as_agui_events(iter(chunks), thread_id="thread-1", run_id="run-1"))


async def as_async_iterator(chunks):
    if hasattr(chunks, "__aiter__"):
        async for chunk in chunks:
            yield chunk
        return
    for chunk in chunks:
        yield chunk


async def drain_async_mapper(chunks):
    return [
        event
        async for event in async_stream_agno_response_as_agui_events(
            as_async_iterator(chunks), thread_id="thread-1", run_id="run-1"
        )
    ]


def drive_async_mapper(chunks):
    return asyncio.run(drain_async_mapper(chunks))


MAPPER_DRIVERS = [drive_sync_mapper, drive_async_mapper]
MAPPER_IDS = ["sync_mapper", "async_mapper"]


def validated(driver):
    """Wrap a driver so the stream it produces is checked against the protocol rules."""

    def run(chunks):
        events = driver(chunks)
        assert_valid_agui_stream(events)
        return events

    return run
