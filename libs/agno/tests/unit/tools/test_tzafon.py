"""Unit tests for TzafonTools."""

import json
import os
from unittest.mock import Mock, patch

import pytest

from agno.media import Image
from agno.tools.function import ToolResult
from agno.tools.tzafon import TzafonTools

TEST_API_KEY = "test_api_key"
TEST_SCREENSHOT_URL = "https://api.tzafon.ai/screenshots/abc.png"


@pytest.fixture
def mock_lightcone():
    """Patch the Lightcone client and return (client, computer) mocks."""
    with patch("agno.tools.tzafon.Lightcone") as mock_lightcone_cls:
        mock_client = Mock()
        mock_computer = Mock()
        mock_computer.screenshot.return_value = {"raw": "result"}
        mock_computer.get_screenshot_url.return_value = TEST_SCREENSHOT_URL
        mock_client.computer.create.return_value = mock_computer
        mock_lightcone_cls.return_value = mock_client
        yield mock_client, mock_computer


@pytest.fixture
def tools(mock_lightcone):
    return TzafonTools(api_key=TEST_API_KEY)


def test_initialization_with_api_key(mock_lightcone):
    tools = TzafonTools(api_key=TEST_API_KEY, kind="desktop")
    assert tools.api_key == TEST_API_KEY
    assert tools.kind == "desktop"
    assert tools._computer is None


def test_initialization_reads_env(mock_lightcone):
    with patch.dict(os.environ, {"TZAFON_API_KEY": "env_key"}, clear=True):
        tools = TzafonTools()
        assert tools.api_key == "env_key"


def test_initialization_without_api_key_raises():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError):
            TzafonTools()


def test_ensure_computer_creates_once(tools, mock_lightcone):
    mock_client, mock_computer = mock_lightcone
    first = tools._ensure_computer()
    second = tools._ensure_computer()
    assert first is mock_computer
    assert second is mock_computer
    mock_client.computer.create.assert_called_once_with(kind="browser")


def test_navigate_to(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    result = json.loads(tools.navigate_to("https://news.ycombinator.com"))
    mock_computer.navigate.assert_called_once_with("https://news.ycombinator.com")
    assert result["status"] == "complete"
    assert result["url"] == "https://news.ycombinator.com"


def test_click(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    tools.click(10, 20)
    mock_computer.click.assert_called_once_with(10, 20)


def test_type_text(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    tools.type_text("hello")
    mock_computer.type.assert_called_once_with("hello")


def test_scroll(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    tools.scroll(0, 100)
    mock_computer.scroll.assert_called_once_with(0, 100, 0, 0)


def test_wait(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    tools.wait(2)
    mock_computer.wait.assert_called_once_with(2)


def test_screenshot_returns_image_and_url(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    result = tools.screenshot()
    assert isinstance(result, ToolResult)
    assert TEST_SCREENSHOT_URL in result.content
    assert result.images is not None
    assert isinstance(result.images[0], Image)
    assert result.images[0].url == TEST_SCREENSHOT_URL
    mock_computer.screenshot.assert_called_once()
    mock_computer.get_screenshot_url.assert_called_once_with({"raw": "result"})


def test_screenshot_error_returns_toolresult(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    mock_computer.screenshot.side_effect = Exception("boom")
    result = tools.screenshot()
    assert isinstance(result, ToolResult)
    assert "Error taking screenshot" in result.content
    assert not result.images


def test_close_session_terminates_and_resets(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    tools._ensure_computer()
    result = json.loads(tools.close_session())
    mock_computer.terminate.assert_called_once()
    assert tools._computer is None
    assert result["status"] == "closed"


def test_close_session_without_computer(tools):
    result = json.loads(tools.close_session())
    assert result["status"] == "closed"
    assert "No active" in result["message"]


@pytest.mark.asyncio
async def test_anavigate_to(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    result = json.loads(await tools.anavigate_to("https://example.com"))
    mock_computer.navigate.assert_called_once_with("https://example.com")
    assert result["status"] == "complete"


@pytest.mark.asyncio
async def test_ascreenshot(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    result = await tools.ascreenshot()
    assert isinstance(result, ToolResult)
    assert result.images[0].url == TEST_SCREENSHOT_URL


@pytest.mark.asyncio
async def test_aclose_session(tools, mock_lightcone):
    _, mock_computer = mock_lightcone
    tools._ensure_computer()
    result = json.loads(await tools.aclose_session())
    mock_computer.terminate.assert_called_once()
    assert result["status"] == "closed"
