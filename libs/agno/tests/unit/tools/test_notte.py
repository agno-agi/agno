"""Unit tests for NotteTools class."""

import json
import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.tools.notte import NotteTools

TEST_API_KEY = os.environ.get("NOTTE_API_KEY", "test_api_key")
TEST_SERVER_URL = os.environ.get("NOTTE_API_URL")


@pytest.fixture
def mock_notte_client():
    """Patch the NotteClient constructor used by NotteTools."""
    with patch("agno.tools.notte.NotteClient") as mock_client_cls:
        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_session(mock_notte_client):
    """Wire a mock RemoteSession onto the mock client."""
    session = Mock()
    session.session_id = "ses_test_123"

    obs = Mock()
    obs.metadata = Mock(url="https://example.com", title="Example")
    obs.space = Mock(description="@B1: Submit\n@I1: Search input")
    obs.screenshot = Mock()
    obs.screenshot.bytes = Mock(return_value=b"\x89PNG\r\n\x1a\n")
    session.observe = Mock(return_value=obs)

    exec_result = Mock(success=True, message="ok")
    session.execute = Mock(return_value=exec_result)
    session.scrape = Mock(return_value="# Page Markdown\n\nHello")
    session.stop = Mock()
    session.start = Mock()

    mock_notte_client.Session = Mock(return_value=session)
    return session


@pytest.fixture
def tools(mock_notte_client, mock_session):
    """A NotteTools instance with a mocked client and session."""
    return NotteTools(api_key=TEST_API_KEY, server_url=TEST_SERVER_URL)


class TestInit:
    def test_init_with_explicit_api_key(self, mock_notte_client):
        t = NotteTools(api_key="explicit_key")
        assert t.api_key == "explicit_key"

    def test_init_reads_env_var(self, mock_notte_client, monkeypatch):
        monkeypatch.setenv("NOTTE_API_KEY", "env_key")
        t = NotteTools()
        assert t.api_key == "env_key"

    def test_missing_api_key_raises(self, mock_notte_client, monkeypatch):
        monkeypatch.delenv("NOTTE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="NOTTE_API_KEY is required"):
            NotteTools()

    def test_default_tools_registered(self, tools):
        names = {fn.__name__ for fn in tools.tools}
        assert names == {
            "navigate_to",
            "screenshot",
            "get_page_content",
            "observe",
            "click",
            "fill",
            "scrape",
            "run_agent",
            "run_function",
            "close_session",
        }

    def test_individual_enable_flags(self, mock_notte_client):
        t = NotteTools(
            api_key=TEST_API_KEY,
            enable_navigate_to=True,
            enable_screenshot=False,
            enable_get_page_content=False,
            enable_observe=False,
            enable_click=False,
            enable_fill=False,
            enable_scrape=False,
            enable_run_agent=False,
            enable_run_function=False,
            enable_close_session=False,
        )
        assert {fn.__name__ for fn in t.tools} == {"navigate_to"}

    def test_all_flag_enables_everything(self, mock_notte_client):
        t = NotteTools(
            api_key=TEST_API_KEY,
            all=True,
            enable_navigate_to=False,
            enable_screenshot=False,
            enable_get_page_content=False,
            enable_observe=False,
            enable_click=False,
            enable_fill=False,
            enable_scrape=False,
            enable_run_agent=False,
            enable_run_function=False,
            enable_close_session=False,
        )
        assert len(t.tools) == 10

    def test_custom_server_url_passed_through(self, mock_notte_client):
        with patch("agno.tools.notte.NotteClient") as cls:
            NotteTools(api_key=TEST_API_KEY, server_url="https://eu.api.notte.cc")
            cls.assert_called_once()
            kwargs = cls.call_args.kwargs
            assert kwargs["server_url"] == "https://eu.api.notte.cc"


class TestNavigateTo:
    def test_navigate_to_starts_session_and_executes_goto(self, tools, mock_session):
        out = tools.navigate_to("https://example.com")
        mock_session.start.assert_called_once()
        mock_session.execute.assert_called_once_with(type="goto", url="https://example.com")
        assert json.loads(out) == {"status": "complete", "url": "https://example.com"}

    def test_navigate_to_handles_error(self, tools, mock_session):
        mock_session.execute.side_effect = RuntimeError("boom")
        out = tools.navigate_to("https://example.com")
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert "boom" in payload["message"]


class TestScreenshot:
    def test_screenshot_writes_bytes_to_path(self, tools, mock_session, tmp_path):
        target = tmp_path / "shot.png"
        out = tools.screenshot(str(target))
        assert json.loads(out) == {"status": "success", "path": str(target)}
        assert target.read_bytes().startswith(b"\x89PNG")


class TestGetPageContent:
    def test_returns_scrape_markdown(self, tools, mock_session):
        out = tools.get_page_content()
        mock_session.scrape.assert_called_once_with(only_main_content=True)
        assert "Page Markdown" in out

    def test_truncates_long_content(self, mock_notte_client, mock_session):
        mock_session.scrape.return_value = "x" * 5000
        t = NotteTools(api_key=TEST_API_KEY, max_content_length=100)
        out = t.get_page_content()
        assert "Content truncated" in out


class TestObserve:
    def test_observe_returns_action_space(self, tools, mock_session):
        out = tools.observe()
        payload = json.loads(out)
        assert payload["url"] == "https://example.com"
        assert payload["title"] == "Example"
        assert "@B1" in payload["action_space"]

    def test_observe_passes_instructions(self, tools, mock_session):
        tools.observe(instructions="Find the search box")
        mock_session.observe.assert_called_with(instructions="Find the search box")


class TestClickFill:
    def test_click_strips_at_prefix(self, tools, mock_session):
        out = tools.click("@B1")
        mock_session.execute.assert_called_with(type="click", id="B1")
        assert json.loads(out)["element_id"] == "B1"

    def test_fill_passes_value(self, tools, mock_session):
        tools.fill("I1", "hello")
        mock_session.execute.assert_called_with(type="fill", id="I1", value="hello")


class TestScrape:
    def test_scrape_markdown_default(self, tools, mock_session):
        out = tools.scrape()
        mock_session.scrape.assert_called_with(only_main_content=True)
        assert "Page Markdown" in out

    def test_scrape_with_instructions_serialises_pydantic(self, tools, mock_session):
        structured = MagicMock()
        structured.data.model_dump_json.return_value = '{"items": [1, 2, 3]}'
        mock_session.scrape.return_value = structured

        out = tools.scrape(instructions="Extract list items")
        mock_session.scrape.assert_called_with(instructions="Extract list items")
        assert json.loads(out) == {"items": [1, 2, 3]}


class TestRunAgent:
    def test_run_agent_invokes_client_agent(self, tools, mock_notte_client, mock_session):
        agent = Mock()
        agent.agent_id = "agt_test"
        agent.run.return_value = Mock(answer="The answer is 42.")
        mock_notte_client.Agent = Mock(return_value=agent)

        out = tools.run_agent(task="Find the price of eggs", url="https://example.com")
        mock_notte_client.Agent.assert_called_once()
        agent.run.assert_called_once_with(task="Find the price of eggs", url="https://example.com")
        payload = json.loads(out)
        assert payload["status"] == "complete"
        assert payload["answer"] == "The answer is 42."
        assert payload["agent_id"] == "agt_test"

    def test_run_agent_respects_reasoning_model(self, mock_notte_client, mock_session):
        t = NotteTools(api_key=TEST_API_KEY, reasoning_model="gemini/gemini-2.5-flash")
        agent = Mock(agent_id="agt", run=Mock(return_value=Mock(answer="ok")))
        mock_notte_client.Agent = Mock(return_value=agent)

        t.run_agent(task="x")
        kwargs = mock_notte_client.Agent.call_args.kwargs
        assert kwargs["reasoning_model"] == "gemini/gemini-2.5-flash"


class TestRunFunction:
    def test_run_function_invokes_client_function(self, tools, mock_notte_client):
        run_result = MagicMock()
        run_result.model_dump_json.return_value = '{"output": "ok", "status": "complete"}'
        function = Mock()
        function.run = Mock(return_value=run_result)
        mock_notte_client.Function = Mock(return_value=function)

        out = tools.run_function(function_id="fn_abc", variables={"store": "xyz"})
        mock_notte_client.Function.assert_called_once_with(function_id="fn_abc")
        function.run.assert_called_once_with(version=None, timeout=None, store="xyz")
        assert json.loads(out) == {"output": "ok", "status": "complete"}

    def test_run_function_handles_error(self, tools, mock_notte_client):
        function = Mock()
        function.run = Mock(side_effect=RuntimeError("function not found"))
        mock_notte_client.Function = Mock(return_value=function)

        out = tools.run_function(function_id="fn_missing")
        payload = json.loads(out)
        assert payload["status"] == "error"
        assert payload["function_id"] == "fn_missing"
        assert "function not found" in payload["message"]


class TestCloseSession:
    def test_close_session_stops_and_resets(self, tools, mock_session):
        tools._ensure_session()
        out = tools.close_session()
        mock_session.stop.assert_called_once()
        assert tools._session is None
        assert json.loads(out)["status"] == "closed"

    def test_close_session_handles_no_session(self, tools):
        out = tools.close_session()
        assert json.loads(out)["status"] == "closed"


@pytest.mark.asyncio
class TestAsync:
    async def test_anavigate_to(self, tools, mock_session):
        out = await tools.anavigate_to("https://example.com")
        mock_session.execute.assert_called_with(type="goto", url="https://example.com")
        assert json.loads(out)["status"] == "complete"

    async def test_aobserve(self, tools, mock_session):
        out = await tools.aobserve()
        assert json.loads(out)["url"] == "https://example.com"

    async def test_aclick(self, tools, mock_session):
        out = await tools.aclick("B1")
        assert json.loads(out)["element_id"] == "B1"

    async def test_afill(self, tools, mock_session):
        await tools.afill("I1", "hello")
        mock_session.execute.assert_called_with(type="fill", id="I1", value="hello")

    async def test_ascrape(self, tools, mock_session):
        out = await tools.ascrape()
        assert "Page Markdown" in out

    async def test_aclose_session(self, tools, mock_session):
        tools._ensure_session()
        out = await tools.aclose_session()
        mock_session.stop.assert_called_once()
        assert json.loads(out)["status"] == "closed"
