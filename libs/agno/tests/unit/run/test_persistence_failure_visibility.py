"""Persistence failures must not be reported as successful runs."""

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import StatementError

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.run.workflow import WorkflowCompletedEvent
from agno.team import Team
from agno.workflow import Workflow


class MockModel(Model):
    def __init__(self) -> None:
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def parse_args(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._response

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._response

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return self._response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._response


def _workflow_step(workflow: Workflow, execution_input: Any, **kwargs: Any) -> Any:
    return "ok"


def _component(kind: str, db: Any) -> Any:
    if kind == "agent":
        return Agent(id="agent", model=MockModel(), db=db, telemetry=False)
    if kind == "team":
        return Team(id="team", name="team", members=[], model=MockModel(), db=db, telemetry=False)
    return Workflow(id="workflow", name="workflow", steps=_workflow_step, db=db, telemetry=False)


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_completed_run_surfaces_run_persistence_failure(kind: str, tmp_path: Any) -> None:
    db = SqliteDb(db_file=str(tmp_path / f"{kind}.db"))
    component = _component(kind, db)

    with pytest.raises(StatementError, match="Decimal"):
        component.run("hello", session_id="session", metadata={"amount": Decimal("12.34")})

    assert db.get_runs(session_id="session") == []


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_failed_second_run_leaves_previous_durable_run_visible(kind: str, tmp_path: Any) -> None:
    db = SqliteDb(db_file=str(tmp_path / f"{kind}-stale.db"))
    component = _component(kind, db)

    first = component.run("first", session_id="session", metadata={"amount": "12.34"})
    before = [run.run_id for run in db.get_runs(session_id="session")]

    with pytest.raises(StatementError, match="Decimal"):
        component.run("second", session_id="session", metadata={"amount": Decimal("12.34")})

    assert before == [first.run_id]
    assert [run.run_id for run in db.get_runs(session_id="session")] == before


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
async def test_async_completed_run_surfaces_run_persistence_failure(kind: str, tmp_path: Any) -> None:
    db = SqliteDb(db_file=str(tmp_path / f"{kind}-async.db"))
    component = _component(kind, db)

    with pytest.raises(StatementError, match="Decimal"):
        await component.arun("hello", session_id="session", metadata={"amount": Decimal("12.34")})

    assert db.get_runs(session_id="session") == []


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
async def test_async_db_completed_run_surfaces_run_persistence_failure(kind: str, tmp_path: Any) -> None:
    db = AsyncSqliteDb(db_file=str(tmp_path / f"{kind}-native-async.db"))
    component = _component(kind, db)

    try:
        with pytest.raises(StatementError, match="Decimal"):
            await component.arun("hello", session_id="session", metadata={"amount": Decimal("12.34")})

        assert await db.get_runs(session_id="session") == []
    finally:
        await db.close()


def test_streaming_workflow_persists_before_completed_event(tmp_path: Any) -> None:
    db = SqliteDb(db_file=str(tmp_path / "workflow-stream.db"))
    workflow = _component("workflow", db)
    events = []

    with pytest.raises(StatementError, match="Decimal"):
        events.extend(workflow.run("hello", session_id="session", metadata={"amount": Decimal("12.34")}, stream=True))

    assert not any(isinstance(event, WorkflowCompletedEvent) for event in events)


async def test_async_streaming_workflow_persists_before_completed_event(tmp_path: Any) -> None:
    db = AsyncSqliteDb(db_file=str(tmp_path / "workflow-stream-async.db"))
    workflow = _component("workflow", db)
    events = []

    try:
        with pytest.raises(StatementError, match="Decimal"):
            async for event in workflow.arun(
                "hello", session_id="session", metadata={"amount": Decimal("12.34")}, stream=True
            ):
                events.append(event)

        assert not any(isinstance(event, WorkflowCompletedEvent) for event in events)
    finally:
        await db.close()


class FailingSessionDb(InMemoryDb):
    def upsert_session(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("session commit failed")


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_session_persistence_failure_propagates(kind: str) -> None:
    component = _component(kind, FailingSessionDb())

    with pytest.raises(RuntimeError, match="session commit failed"):
        component.run("hello", session_id="session")


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
async def test_async_session_persistence_failure_propagates(kind: str) -> None:
    component = _component(kind, FailingSessionDb())

    with pytest.raises(RuntimeError, match="session commit failed"):
        await component.arun("hello", session_id="session")


class FailingAsyncSessionDb(AsyncSqliteDb):
    async def upsert_session(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("async session commit failed")


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
async def test_async_db_session_persistence_failure_propagates(kind: str, tmp_path: Any) -> None:
    db = FailingAsyncSessionDb(db_file=str(tmp_path / f"{kind}-session-async.db"))
    component = _component(kind, db)

    try:
        with pytest.raises(RuntimeError, match="async session commit failed"):
            await component.arun("hello", session_id="session")
    finally:
        await db.close()


class LegacyRunDb(InMemoryDb):
    def upsert_run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_legacy_adapter_without_run_store_remains_supported(kind: str) -> None:
    component = _component(kind, LegacyRunDb())

    result = component.run("hello", session_id="session")

    assert result.status == RunStatus.completed


class LegacyAsyncRunDb(AsyncSqliteDb):
    async def upsert_run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
async def test_legacy_async_adapter_without_run_store_remains_supported(kind: str, tmp_path: Any) -> None:
    db = LegacyAsyncRunDb(db_file=str(tmp_path / f"{kind}-legacy-async.db"))
    component = _component(kind, db)

    try:
        result = await component.arun("hello", session_id="session")

        assert result.status == RunStatus.completed
    finally:
        await db.close()
