"""External agents don't support background=True; the resumable streaming route
must degrade to inline SSE instead of forwarding raw event objects to Starlette
(which crashes with "'RunStartedEvent' object has no attribute 'encode'")."""

import tempfile
from dataclasses import dataclass
from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient

from agno.agents.base import BaseExternalAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.run.agent import RunContentEvent, RunOutputEvent


@dataclass
class EchoAgent(BaseExternalAgent):
    framework: str = "test-framework"

    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        return f"echo: {input}"

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        yield RunContentEvent(run_id=kwargs.get("run_id", ""), content=f"echo: {input}")


@pytest.fixture
def client():
    tmp = tempfile.mkdtemp()
    db = SqliteDb(db_file=f"{tmp}/os.db")
    agent = EchoAgent(name="Echo", id="echo-agent", db=db)
    app = AgentOS(id="test-os", db=db, agents=[agent]).get_app()
    return TestClient(app, raise_server_exceptions=False)


def test_background_stream_degrades_to_inline_sse(client):
    response = client.post(
        "/agents/echo-agent/runs",
        data={"message": "hi", "stream": "true", "background": "true"},
    )
    assert response.status_code == 200
    events = [line for line in response.text.splitlines() if line.startswith("event:")]
    assert any("RunStarted" in line for line in events)
    assert any("RunCompleted" in line for line in events)


def test_plain_stream_still_works(client):
    response = client.post(
        "/agents/echo-agent/runs",
        data={"message": "hi", "stream": "true"},
    )
    assert response.status_code == 200
    assert "RunCompleted" in response.text
