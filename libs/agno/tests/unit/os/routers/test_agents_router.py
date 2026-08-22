import json
from types import SimpleNamespace

import pytest

from agno.os.routers.agents import router as agents_router
from agno.run.base import RunStatus


class _DatabaseAgent:
    def __init__(self, status):
        self.status = status

    async def aget_run_output(self, **kwargs):
        return SimpleNamespace(status=self.status, events=[])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RunStatus.completed, RunStatus.completed.value),
        (RunStatus.completed.value, RunStatus.completed.value),
    ],
)
async def test_resume_database_replay_accepts_enum_and_string_status(monkeypatch, status, expected):
    monkeypatch.setattr(
        agents_router.event_buffer,
        "get_run_status",
        lambda run_id: None,
    )

    chunks = [
        chunk
        async for chunk in agents_router._resume_stream_generator(
            agent=_DatabaseAgent(status),
            run_id="run-1",
            last_event_index=None,
            session_id="session-1",
        )
    ]

    payload = json.loads(chunks[0].split("data: ", maxsplit=1)[1])
    assert payload["event"] == "replay"
    assert payload["status"] == expected
    assert payload["total_events"] == 0
