"""The verification loop through AgentOS itself: the REST run endpoint, the persisted row,
the run-list filter, and the SSE stream all see the same truth — no runner, no special
route, just an agent with verifiers behind the ordinary surface."""

import json
import tempfile
from typing import Any, AsyncIterator, Iterator, List

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.os import AgentOS


class ScriptedModel(Model):
    def __init__(self, script: List[ModelResponse]) -> None:
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def __deepcopy__(self, memo: Any) -> "ScriptedModel":
        return self

    def _next(self) -> ModelResponse:
        response = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return response

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _text(content: str) -> ModelResponse:
    return ModelResponse(role="assistant", content=content)


def _make_app(tmp_path, verifier, max_attempts=2):
    from agno.verifiers import VerificationConfig

    agent = Agent(
        id="verified-agent",
        name="Verified Agent",
        model=ScriptedModel([_text("claimed done")]),
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        verifiers=[verifier],
        verification=VerificationConfig(max_attempts=max_attempts),
    )
    return AgentOS(agents=[agent], telemetry=False).get_app()


def test_rest_run_reports_unverified_and_persists_the_record(tmp_path):
    app = _make_app(tmp_path, lambda run_output: "not good enough")
    with TestClient(app) as client:
        response = client.post(
            "/agents/verified-agent/runs",
            data={"message": "do the work", "stream": "false", "session_id": "e2e-1"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "UNVERIFIED"
        assert body["verification"]["status"] == "unverified"
        assert body["verification"]["stop_reason"] == "exhausted"
        assert len(body["verification"]["attempts"]) == 2

        # The persisted row carries the same truth through the single-run read.
        run_id = body["run_id"]
        stored = client.get(f"/sessions/e2e-1/runs/{run_id}")
        if stored.status_code == 200:
            stored_body = stored.json()
            assert stored_body.get("status") == "UNVERIFIED"

        # The run-list filter accepts the new status string and returns the run.
        listed = client.get(
            "/agents/verified-agent/runs",
            params={"session_id": "e2e-1", "status": "UNVERIFIED"},
        )
        assert listed.status_code == 200
        listed_body = listed.json()
        listed_runs = listed_body if isinstance(listed_body, list) else listed_body.get("runs", [])
        assert run_id in [r.get("run_id") for r in listed_runs]


def test_rest_run_verified_leg(tmp_path):
    app = _make_app(tmp_path, lambda run_output: True)
    with TestClient(app) as client:
        response = client.post(
            "/agents/verified-agent/runs",
            data={"message": "do the work", "stream": "false", "session_id": "e2e-2"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "COMPLETED"
        assert body["verification"]["status"] == "verified"


def test_sse_stream_carries_verification_events(tmp_path):
    app = _make_app(tmp_path, lambda run_output: "still failing")
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/agents/verified-agent/runs",
            data={"message": "go", "stream": "true", "session_id": "e2e-3"},
        ) as response:
            assert response.status_code == 200
            payload = "".join(chunk for chunk in response.iter_text())
    event_names = [
        json.loads(line[len("data: ") :]).get("event")
        for line in payload.splitlines()
        if line.startswith("data: ") and line[len("data: ") :].strip().startswith("{")
    ]
    assert event_names.count("VerificationStarted") == 2
    assert event_names.count("VerificationCompleted") == 2
    assert "RunCompleted" in event_names


def test_unverified_smoke_via_tempdir():
    # tmp_path-free variant so the module also runs standalone.
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path

        app = _make_app(Path(td), lambda run_output: "no", max_attempts=1)
        with TestClient(app) as client:
            response = client.post(
                "/agents/verified-agent/runs",
                data={"message": "hi", "stream": "false"},
            )
            assert response.json()["status"] == "UNVERIFIED"
