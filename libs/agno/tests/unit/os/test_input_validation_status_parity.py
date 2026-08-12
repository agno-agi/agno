"""One invalid payload, one status: 400 on every pre-acceptance door.

The same schema-violating input used to answer four different shapes:
422 from the durable seams (whose comments falsely claimed the inline path
422s), 400 from the inline non-stream door (InputCheckError only - a bare
schema ValueError was uncaught and 500ed), 500 from the non-durable
background fallback (no try/except at all), and 200 + SSE error frame when
streaming. The streaming shape is the SSE contract (headers already sent);
every other pre-acceptance door now answers 400.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.exceptions import InputCheckError
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS


class StrictInput(BaseModel):
    quantity: int
    reason: str


@pytest.fixture()
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db, input_schema=StrictInput)
    app = AgentOS(agents=[agent], telemetry=False).get_app()
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(app=app, client=client)


class TestSeamAnswers400:
    def test_durable_seam_schema_violation_is_400(self, harness):
        """The seam used to 422 on the false premise that the inline path
        did; the inline contract is 400 and the seam must match it."""
        harness.app.state.queue_worker = SimpleNamespace(store=InMemoryQueueStore(), config=QueueConfig(durable=True))
        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": "not the schema shape", "stream": "false", "background": "true"},
        )
        assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text[:200]}"
        assert "schema" in resp.json()["detail"].lower()


class TestInlineDoorsAnswer400:
    def test_inline_bare_value_error_is_400(self, harness, monkeypatch):
        """A bare schema ValueError from the dispatch was uncaught -> 500."""

        async def raising_arun(self, **kwargs):
            raise ValueError("Input required when input_schema is set")

        monkeypatch.setattr(Agent, "arun", raising_arun)
        resp = harness.client.post(
            "/agents/qa-agent/runs", data={"message": "hi", "stream": "false", "background": "false"}
        )
        assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text[:200]}"

    def test_background_fallback_input_error_is_400(self, harness, monkeypatch):
        """No queue worker: background=true drops to the non-durable
        in-process fallback, which had no try/except at all -> 500."""

        async def raising_arun(self, **kwargs):
            raise InputCheckError("input not allowed by schema")

        monkeypatch.setattr(Agent, "arun", raising_arun)
        resp = harness.client.post(
            "/agents/qa-agent/runs", data={"message": "hi", "stream": "false", "background": "true"}
        )
        assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text[:200]}"
