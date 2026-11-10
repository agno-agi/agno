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
    def test_inline_schema_violation_is_400(self, harness):
        """The inline non-stream door pre-validates with the seams' shared
        check: a schema violation answers 400 BEFORE dispatch (it used to
        surface as the dispatch's bare ValueError -> 500)."""
        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": "not the schema shape", "stream": "false", "background": "false"},
        )
        assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text[:200]}"
        assert "schema" in resp.json()["detail"].lower()

    def test_background_fallback_schema_violation_is_400(self, harness):
        """No queue worker: background=true drops to the non-durable
        fallback, which had no input handling at all -> 500."""
        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": "not the schema shape", "stream": "false", "background": "true"},
        )
        assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text[:200]}"

    def test_background_fallback_guardrail_refusal_is_400(self, harness, monkeypatch):
        async def refusing_arun(self, **kwargs):
            raise InputCheckError("input not allowed")

        monkeypatch.setattr(Agent, "arun", refusing_arun)
        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": '{"quantity": 1, "reason": "ok"}', "stream": "false", "background": "true"},
        )
        assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text[:200]}"


class TestInternalValueErrorStays500:
    def test_dispatch_value_error_is_not_misclassified_as_client_error(self, harness, monkeypatch):
        """A downstream ValueError (e.g. storage code) is a SERVER failure:
        catching ValueError at the router would answer 400 with the raw
        message - misclassifying the failure and echoing internals the 5xx
        policy suppresses."""

        async def broken_arun(self, **kwargs):
            raise ValueError("db not initialized at postgresql://ai:secret@db.internal/ai")

        monkeypatch.setattr(Agent, "arun", broken_arun)
        resp = harness.client.post(
            "/agents/qa-agent/runs",
            data={"message": '{"quantity": 1, "reason": "ok"}', "stream": "false", "background": "false"},
        )
        assert resp.status_code == 500, f"an internal ValueError must stay a 500, got {resp.status_code}"
        assert "secret" not in resp.text, "the 500 body must not echo the exception message"
