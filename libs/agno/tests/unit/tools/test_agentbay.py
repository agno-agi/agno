"""Unit tests for AgentBayTools."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock agentbay and submodules before any agno.tools.agentbay import
mock_agentbay = MagicMock()
mock_agentbay.ActOptions = MagicMock()
mock_agentbay.BrowserOption = MagicMock()
mock_agentbay.BrowserViewport = MagicMock()
mock_agentbay.ExtractOptions = MagicMock()
mock_agentbay.MouseButton = MagicMock()
mock_agentbay.ObserveOptions = MagicMock()
mock_agentbay.AsyncAgentBay = MagicMock()
mock_agentbay.ContextSync = MagicMock()
mock_agentbay.CreateSessionParams = MagicMock()

mock_agentbay_api = MagicMock()
mock_agentbay_api_models = MagicMock()
mock_agentbay_api_models.GetAndLoadInternalContextRequest = MagicMock()
mock_agentbay_api.models = mock_agentbay_api_models

sys.modules["agentbay"] = mock_agentbay
sys.modules["agentbay.api"] = mock_agentbay_api
sys.modules["agentbay.api.models"] = mock_agentbay_api_models

# Import after mocking so agentbay is not required at collect time
from agno.tools.agentbay import AgentBayTools  # noqa: E402


@pytest.fixture
def mock_agent():
    """Create a mock agent with session_state."""
    agent = MagicMock()
    agent.session_state = {}
    return agent


def _make_mock_session(session_id: str = "s-test-123"):
    """Create a mock AgentBay session with code and command interfaces."""
    session = MagicMock()
    session.session_id = session_id
    session._get_session_id = MagicMock(return_value=session_id)

    mock_code = MagicMock()
    mock_code.run_code = AsyncMock(return_value=MagicMock(success=True, result="ok"))
    session.code = mock_code

    mock_command = MagicMock()
    mock_command.execute_command = AsyncMock(return_value=MagicMock(success=True, output="done"))
    session.command = mock_command

    return session


@pytest.fixture
def mock_session_manager():
    """Create a mock AgentBaySessionManager."""
    mock_sm = MagicMock()
    mock_sm.start = AsyncMock()
    mock_sm.agent_bay = MagicMock()
    mock_session = _make_mock_session()
    mock_sm.get_or_create_session = AsyncMock(return_value=mock_session)
    mock_sm.get_session = AsyncMock(return_value=mock_session)
    mock_sm.create_session = AsyncMock(return_value=mock_session)
    mock_sm.delete_session = AsyncMock(return_value=True)
    mock_sm._build_session_key = MagicMock(return_value="key_1")
    return mock_sm


class TestAgentBayTools:
    """Test AgentBayTools class."""

    def test_initialization_with_api_key(self):
        """Test initialization with API key."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "test-key"}):
            with patch("agno.tools.agentbay.toolkit.AgentBaySessionManager") as mock_sm_class:
                mock_sm_class.return_value = MagicMock()
                tools = AgentBayTools(api_key="test-key")
                assert tools.api_key == "test-key"
                assert tools.default_environment == "linux_latest"

    def test_initialization_with_env_var(self):
        """Test initialization with env var."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "env-key"}):
            with patch("agno.tools.agentbay.toolkit.AgentBaySessionManager") as mock_sm_class:
                mock_sm_class.return_value = MagicMock()
                tools = AgentBayTools()
                assert tools.api_key == "env-key"

    def test_initialization_without_api_key(self):
        """Test initialization without API key raises ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="AGENTBAY_API_KEY not set"):
                AgentBayTools()

    @pytest.mark.asyncio
    async def test_create_sandbox_returns_sandbox_id(self, mock_agent, mock_session_manager):
        """Test create_sandbox returns message with sandbox_id."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "test-key"}):
            with patch(
                "agno.tools.agentbay.toolkit.AgentBaySessionManager",
                return_value=mock_session_manager,
            ):
                tools = AgentBayTools(api_key="test-key")
                result = await tools.create_sandbox(mock_agent, environment="code_latest")
                assert "sandbox_id" in result
                assert "s-test-123" in result
                mock_session_manager.start.assert_called()
                mock_session_manager.get_or_create_session.assert_called()

    @pytest.mark.asyncio
    async def test_run_code_success(self, mock_agent, mock_session_manager):
        """Test run_code with valid sandbox_id and code."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "test-key"}):
            with patch(
                "agno.tools.agentbay.toolkit.AgentBaySessionManager",
                return_value=mock_session_manager,
            ):
                tools = AgentBayTools(
                    api_key="test-key",
                    enable_code_execution=True,
                )
                result = await tools.run_code(
                    mock_agent,
                    code="print(1+1)",
                    sandbox_id="s-test-123",
                    environment="code_latest",
                )
                assert "successful" in result.lower() or "ok" in result
                mock_session_manager.get_session.assert_called_with("s-test-123")
                session = mock_session_manager.get_or_create_session.return_value
                session.code.run_code.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_code_missing_sandbox_id(self, mock_agent, mock_session_manager):
        """Test run_code without sandbox_id returns error message."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "test-key"}):
            with patch(
                "agno.tools.agentbay.toolkit.AgentBaySessionManager",
                return_value=mock_session_manager,
            ):
                tools = AgentBayTools(
                    api_key="test-key",
                    enable_code_execution=True,
                )
                result = await tools.run_code(
                    mock_agent,
                    code="print(1)",
                    sandbox_id="",
                    environment="code_latest",
                )
                assert "status" in result or "error" in result.lower()
                assert "create_sandbox" in result or "sandbox_id" in result

    @pytest.mark.asyncio
    async def test_run_shell_command_success(self, mock_agent, mock_session_manager):
        """Test run_shell_command with valid sandbox_id."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "test-key"}):
            with patch(
                "agno.tools.agentbay.toolkit.AgentBaySessionManager",
                return_value=mock_session_manager,
            ):
                tools = AgentBayTools(api_key="test-key")
                result = await tools.run_shell_command(
                    mock_agent,
                    command="ls -la",
                    sandbox_id="s-test-123",
                )
                assert "successfully" in result.lower() or "done" in result
                session = mock_session_manager.get_or_create_session.return_value
                session.command.execute_command.assert_called_once_with("ls -la")

    @pytest.mark.asyncio
    async def test_run_shell_command_missing_sandbox_id(self, mock_agent, mock_session_manager):
        """Test run_shell_command without sandbox_id returns error."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "test-key"}):
            with patch(
                "agno.tools.agentbay.toolkit.AgentBaySessionManager",
                return_value=mock_session_manager,
            ):
                tools = AgentBayTools(api_key="test-key")
                result = await tools.run_shell_command(
                    mock_agent,
                    command="echo hi",
                    sandbox_id="",
                )
                assert "status" in result or "error" in result.lower()

    def test_require_sandbox_id_valid(self):
        """Test _require_sandbox_id with non-empty sandbox_id."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "test-key"}):
            with patch("agno.tools.agentbay.toolkit.AgentBaySessionManager") as mock_sm_class:
                mock_sm_class.return_value = MagicMock()
                tools = AgentBayTools(api_key="test-key")
                sid, err = tools._require_sandbox_id("s-123", "hint")
                assert sid == "s-123"
                assert err is None

    def test_require_sandbox_id_empty(self):
        """Test _require_sandbox_id with empty sandbox_id returns error."""
        with patch.dict("os.environ", {"AGENTBAY_API_KEY": "test-key"}):
            with patch("agno.tools.agentbay.toolkit.AgentBaySessionManager") as mock_sm_class:
                mock_sm_class.return_value = MagicMock()
                tools = AgentBayTools(api_key="test-key")
                sid, err = tools._require_sandbox_id("", "hint")
                assert sid is None
                assert err is not None
                assert "sandbox_id" in err
