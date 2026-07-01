"""Regression tests for the eval router's temporary model override handling.

Covers #8655: POST /eval-runs temporarily swaps the target agent/team model when
``model_id`` is supplied. The original model must be restored on the shared
in-memory agent/team even when the eval run fails, otherwise a single failed
request silently changes the model for every later run in the same process.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.db.schemas.evals import EvalType
from agno.os.routers.evals import get_eval_router
from agno.os.routers.evals.schemas import EvalSchema
from agno.os.settings import AgnoAPISettings


def _make_async_db() -> MagicMock:
    db = MagicMock(spec=AsyncBaseDb)
    db.id = "test-db"
    return db


def _build_client(agent: Agent) -> TestClient:
    app = FastAPI()
    router = get_eval_router(dbs={"test-db": [_make_async_db()]}, agents=[agent], settings=AgnoAPISettings())
    app.include_router(router)
    return TestClient(app)


def _agent_with_model(model_id: str = "model-a", provider: str = "openai") -> Agent:
    agent = Agent(name="test-agent", id="test-agent-id")
    agent.model = SimpleNamespace(id=model_id, provider=provider)  # type: ignore[assignment]
    return agent


def test_model_override_restored_when_eval_fails():
    """A failed eval run must not leave the temporary override model on the agent."""
    agent = _agent_with_model()
    client = _build_client(agent)

    override_model = SimpleNamespace(id="model-b", provider="openai")
    with patch("agno.os.routers.evals.evals.get_model", return_value=override_model):
        # expected_output is intentionally omitted, so accuracy eval raises 400
        # after the temporary model has already been applied.
        response = client.post(
            "/eval-runs?db_id=test-db",
            json={
                "agent_id": "test-agent-id",
                "eval_type": "accuracy",
                "input": "What is 2 + 2?",
                "model_id": "model-b",
                "model_provider": "openai",
            },
        )

    assert response.status_code == 400
    assert agent.model.id == "model-a"
    assert agent.model.provider == "openai"


def test_model_override_restored_on_success():
    """The override is also restored on the happy path (guards the shared restore)."""
    agent = _agent_with_model()
    client = _build_client(agent)

    override_model = SimpleNamespace(id="model-b", provider="openai")

    # agent is a shared mutable object, so capture the model in effect *during*
    # the eval rather than reading it back after the restore has run.
    model_id_during_eval = {}

    eval_result = EvalSchema(id="eval-1", eval_type=EvalType.ACCURACY, eval_data={})

    async def _capture_model(*args, **kwargs):
        model_id_during_eval["value"] = kwargs["agent"].model.id
        return eval_result

    with (
        patch("agno.os.routers.evals.evals.get_model", return_value=override_model),
        patch("agno.os.routers.evals.evals.run_accuracy_eval", new=AsyncMock(side_effect=_capture_model)),
    ):
        response = client.post(
            "/eval-runs?db_id=test-db",
            json={
                "agent_id": "test-agent-id",
                "eval_type": "accuracy",
                "input": "What is 2 + 2?",
                "expected_output": "4",
                "model_id": "model-b",
                "model_provider": "openai",
            },
        )

    assert response.status_code == 200
    # The eval saw the overridden model while running...
    assert model_id_during_eval["value"] == "model-b"
    # ...and the agent is back to its original model afterwards.
    assert agent.model.id == "model-a"
