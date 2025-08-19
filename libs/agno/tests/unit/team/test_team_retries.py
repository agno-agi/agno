import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.exceptions import ModelProviderError, StopAgentRun
from agno.models.base import Model
from agno.team.team import Team


@pytest.fixture
def mock_model():
    model = MagicMock(spec=Model)
    model.id = "mock_model"
    model.provider = "mock_provider"
    model.aresponse = AsyncMock()
    return model


@pytest.fixture
def team(mock_model):
    agent = Agent(name="Test Agent", model=mock_model)
    return Team(
        members=[agent],
        model=mock_model,
        retries=3,
        delay_between_retries=0.01,
        exponential_backoff=True,
    )


def test_team_run_with_retries(team, mock_model, mocker):
    """Test that a team run retries on failure and eventually succeeds."""
    # Mock the model to fail twice and then succeed
    mock_model.response.side_effect = [
        ModelProviderError("Failed"),
        ModelProviderError("Failed"),
        MagicMock(),
    ]
    mocker.patch("time.sleep")

    team.run("Hello")

    assert mock_model.response.call_count == 3
    time.sleep.assert_any_call(0.01)  # 2**0 * 0.01
    time.sleep.assert_any_call(0.02)  # 2**1 * 0.01


def test_team_run_with_retries_fail(team, mock_model, mocker):
    """Test that a team run fails after all retries."""
    mock_model.response.side_effect = ModelProviderError("Failed")
    mocker.patch("time.sleep")

    with pytest.raises(ModelProviderError):
        team.run("Hello")

    assert mock_model.response.call_count == 4
    time.sleep.assert_any_call(0.01)  # 2**0 * 0.01
    time.sleep.assert_any_call(0.02)  # 2**1 * 0.01
    time.sleep.assert_any_call(0.04)  # 2**2 * 0.01


def test_team_run_with_exponential_backoff_disabled(team, mock_model, mocker):
    """Test that a team run retries with a fixed delay when exponential backoff is disabled."""
    team.exponential_backoff = False
    mock_model.response.side_effect = [
        ModelProviderError("Failed"),
        ModelProviderError("Failed"),
        MagicMock(),
    ]
    mocker.patch("time.sleep")

    team.run("Hello")

    assert mock_model.response.call_count == 3
    time.sleep.assert_any_call(0.01)
    assert time.sleep.call_count == 2


@pytest.mark.asyncio
async def test_team_arun_with_retries(team, mock_model, mocker):
    """Test that an async team run retries on failure and eventually succeeds."""
    # Mock the async response to fail twice and then succeed
    mock_model.aresponse.side_effect = [
        ModelProviderError("Failed"),
        ModelProviderError("Failed"),
        AsyncMock(),
    ]
    mocker.patch("asyncio.sleep", new_callable=AsyncMock)

    await team.arun("Hello")

    assert mock_model.aresponse.call_count == 3
    asyncio.sleep.assert_any_call(0.01)  # 2**0 * 0.01
    asyncio.sleep.assert_any_call(0.02)  # 2**1 * 0.01


@pytest.mark.asyncio
async def test_team_arun_with_retries_fail(team, mock_model, mocker):
    """Test that an async team run fails after all retries."""
    mock_model.aresponse.side_effect = ModelProviderError("Failed")
    mocker.patch("asyncio.sleep", new_callable=AsyncMock)

    with pytest.raises(ModelProviderError):
        await team.arun("Hello")

    assert mock_model.aresponse.call_count == 4
    asyncio.sleep.assert_any_call(0.01)
    asyncio.sleep.assert_any_call(0.02)
    asyncio.sleep.assert_any_call(0.04)


@pytest.mark.asyncio
async def test_team_arun_with_exponential_backoff_disabled(team, mock_model, mocker):
    """Test that an async team run retries with a fixed delay when exponential backoff is disabled."""
    team.exponential_backoff = False
    mock_model.aresponse.side_effect = [
        ModelProviderError("Failed"),
        ModelProviderError("Failed"),
        AsyncMock(),
    ]
    mocker.patch("asyncio.sleep", new_callable=AsyncMock)

    await team.arun("Hello")

    assert mock_model.aresponse.call_count == 3
    asyncio.sleep.assert_any_call(0.01)
    assert asyncio.sleep.call_count == 2


def test_team_run_with_stop_agent_run(team, mock_model):
    """Test that a team run does not retry on StopAgentRun exception."""
    mock_model.response.side_effect = StopAgentRun("Stopped")

    team.run("Hello")

    assert mock_model.response.call_count == 1


@pytest.mark.asyncio
async def test_team_arun_with_stop_agent_run(team, mock_model):
    """Test that an async team run does not retry on StopAgentRun exception."""
    mock_model.aresponse.side_effect = StopAgentRun("Stopped")

    await team.arun("Hello")

    assert mock_model.aresponse.call_count == 1
