from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agno.os.routers.agents import sandbox


@pytest.mark.asyncio
@pytest.mark.parametrize("durable, serializes_sessions", [(False, True), (True, False), (True, None)])
async def test_sandbox_submission_requires_durable_session_admission(durable, serializes_sessions):
    worker = SimpleNamespace(
        config=SimpleNamespace(durable=durable, redis=None),
        store=SimpleNamespace(serializes_sessions=serializes_sessions),
    )
    with pytest.raises(
        ValueError, match="^Sandbox API execution requires a durable queue with shared session admission$"
    ):
        await sandbox.enqueue_sandbox_run(Mock(), worker, input="hello", session_id="session", user_id=None, kwargs={})
