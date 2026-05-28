from unittest.mock import patch

from agno.agent.agent import Agent
from agno.os import AgentOS


def test_accuracy_evals_telemetry():
    """Test that telemetry logging is called when initializing an AgentOS instance."""
    agent = Agent()

    # Mock the API call that gets made when telemetry is enabled
    with patch("agno.api.os.log_os_telemetry") as mock_create:
        os = AgentOS(id="test", agents=[agent])

        # Assert telemetry is active by default
        assert os.telemetry

        # Verify API was called with correct parameters
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]["launch"]
        assert call_args.os_id == "test"
