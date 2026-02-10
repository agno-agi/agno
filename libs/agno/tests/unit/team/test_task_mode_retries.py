"""Unit tests for retry logic in task mode (_run_tasks / _arun_tasks)."""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, List
from unittest.mock import patch

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.team.mode import TeamMode


@dataclass
class _StubModel(Model):
    """Minimal concrete Model for unit tests. Delegates response/aresponse to a callable."""

    id: str = "stub-model"
    provider: str = "stub"
    supports_native_structured_outputs: bool = False

    # Callables set by each test to control behaviour
    _response_fn: Any = field(default=None, repr=False)
    _aresponse_fn: Any = field(default=None, repr=False)

    # Abstract method stubs (not used — we override response/aresponse)
    def invoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        raise NotImplementedError

    def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError  # type: ignore

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError

    # Override the high-level methods that _run_tasks calls directly
    def response(self, **kwargs) -> ModelResponse:
        return self._response_fn(**kwargs)

    async def aresponse(self, **kwargs) -> ModelResponse:
        return await self._aresponse_fn(**kwargs)


def _make_model_response(content: str = "Task completed.") -> ModelResponse:
    """Create a minimal ModelResponse suitable for _update_run_response."""
    return ModelResponse(content=content, role="assistant")


def _make_task_mode_team(model: Model, **kwargs):
    """Create a task mode team with sensible test defaults."""
    from agno.team.team import Team

    member = Agent(name="worker", role="worker")
    defaults = dict(
        name="Task Retry Team",
        members=[member],
        model=model,
        mode=TeamMode.tasks,
        max_iterations=1,
        delay_between_retries=0,
    )
    defaults.update(kwargs)
    return Team(**defaults)


class TestTaskModeRetry:
    """Tests that task mode model calls respect team.retries."""

    def test_retries_on_transient_failure(self):
        """Model call fails once, succeeds on retry — response should be completed."""
        attempt_count = {"count": 0}

        def mock_response(**kwargs):
            attempt_count["count"] += 1
            if attempt_count["count"] < 2:
                raise Exception("Simulated transient failure")
            return _make_model_response()

        model = _StubModel(_response_fn=mock_response)
        team = _make_task_mode_team(model, retries=2)

        response = team.run("Do something")

        assert attempt_count["count"] == 2
        assert response is not None
        assert response.status == RunStatus.completed

    def test_retry_with_exponential_backoff(self):
        """Verify exponential backoff delays are applied between retries."""
        attempt_count = {"count": 0}

        def mock_response(**kwargs):
            attempt_count["count"] += 1
            if attempt_count["count"] < 3:
                raise Exception("Simulated failure")
            return _make_model_response()

        model = _StubModel(_response_fn=mock_response)
        team = _make_task_mode_team(
            model,
            retries=2,
            delay_between_retries=1,
            exponential_backoff=True,
        )

        with patch("agno.team._run.time.sleep") as mock_sleep:
            response = team.run("Do something")

        assert attempt_count["count"] == 3
        assert response.status == RunStatus.completed
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0][0][0] == 1  # 2^0 * 1
        assert mock_sleep.call_args_list[1][0][0] == 2  # 2^1 * 1

    def test_retry_exhausted_returns_error(self):
        """When all retry attempts fail, response should have error status."""

        def mock_response(**kwargs):
            raise Exception("Persistent failure")

        model = _StubModel(_response_fn=mock_response)
        team = _make_task_mode_team(model, retries=2)

        response = team.run("Do something")

        assert response.status == RunStatus.error
        assert "Persistent failure" in str(response.content)

    def test_no_retries_by_default(self):
        """With retries=0 (default), a single failure should immediately error."""
        attempt_count = {"count": 0}

        def mock_response(**kwargs):
            attempt_count["count"] += 1
            raise Exception("Single failure")

        model = _StubModel(_response_fn=mock_response)
        team = _make_task_mode_team(model, retries=0)

        response = team.run("Do something")

        assert attempt_count["count"] == 1
        assert response.status == RunStatus.error


class TestTaskModeAsyncRetry:
    """Tests that async task mode model calls respect team.retries."""

    @pytest.mark.asyncio
    async def test_async_retries_on_transient_failure(self):
        """Async model call fails once, succeeds on retry."""
        attempt_count = {"count": 0}

        async def mock_aresponse(**kwargs):
            attempt_count["count"] += 1
            if attempt_count["count"] < 2:
                raise Exception("Simulated transient failure")
            return _make_model_response()

        model = _StubModel(_aresponse_fn=mock_aresponse)
        team = _make_task_mode_team(model, retries=2)

        response = await team.arun("Do something")

        assert attempt_count["count"] == 2
        assert response is not None
        assert response.status == RunStatus.completed

    @pytest.mark.asyncio
    async def test_async_retry_exhausted_returns_error(self):
        """When all async retry attempts fail, response should have error status."""

        async def mock_aresponse(**kwargs):
            raise Exception("Persistent async failure")

        model = _StubModel(_aresponse_fn=mock_aresponse)
        team = _make_task_mode_team(model, retries=2)

        response = await team.arun("Do something")

        assert response.status == RunStatus.error
        assert "Persistent async failure" in str(response.content)
