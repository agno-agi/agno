from unittest.mock import MagicMock, patch

from agno.agent.agent import Agent
from agno.os import AgentOS


def test_accuracy_evals_telemetry():
    """Test that telemetry logging is called when initializing an AgentOS instance."""
    agent = Agent()

    mock_executor = MagicMock()

    # Mock the executor so we can verify submit was called
    with patch("agno.api._executor.get_telemetry_executor", return_value=mock_executor):
        os = AgentOS(id="test", agents=[agent])

        # Assert telemetry is active by default
        assert os.telemetry

        # Verify submit was called on the executor
        mock_executor.submit.assert_called_once()
        call_args = mock_executor.submit.call_args
        # First positional arg is the function, keyword arg is launch
        assert call_args.kwargs["launch"].os_id == "test"
