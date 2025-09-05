from unittest.mock import Mock

from agno.utils import log as log_module
from agno.utils.log import configure_agno_logging


def test_configure_agno_logging_sets_global_logger():
    """Test that configure_agno_logging can set the global logger."""
    mock_logger = Mock()
    original_logger = log_module.logger

    try:
        # Configure Agno to use the custom logger and assert it works
        configure_agno_logging(custom_default_logger=mock_logger)
        assert log_module.logger is mock_logger

        # Import our general log_info, call it and assert it used our custom logger
        from agno.utils.log import log_info

        log_info("Test message")

        mock_logger.info.assert_called_once_with("Test message")

    finally:
        log_module.logger = original_logger


def test_configure_agno_logging_sets_specialized_loggers():
    """Test that configure_agno_logging can set agent_logger, team_logger, and workflow_logger."""
    mock_agent_logger = Mock()
    mock_team_logger = Mock()
    mock_workflow_logger = Mock()

    original_agent_logger = log_module.agent_logger
    original_team_logger = log_module.team_logger
    original_workflow_logger = log_module.workflow_logger

    try:
        configure_agno_logging(
            custom_agent_logger=mock_agent_logger,
            custom_team_logger=mock_team_logger,
            custom_workflow_logger=mock_workflow_logger,
        )
        assert log_module.agent_logger is mock_agent_logger
        assert log_module.team_logger is mock_team_logger
        assert log_module.workflow_logger is mock_workflow_logger

    finally:
        log_module.agent_logger = original_agent_logger
        log_module.team_logger = original_team_logger
        log_module.workflow_logger = original_workflow_logger
