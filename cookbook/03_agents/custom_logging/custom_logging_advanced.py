"""Example showing how to use multiple custom loggers with Agno.

This is useful for advanced scenarios where you want to use different loggers for different parts of Agno."""

import logging

from agno.agent import Agent
from agno.team import Team
from agno.utils.log import configure_agno_logging


def get_custom_agent_logger():
    """Return an example custom agent logger."""
    custom_logger = logging.getLogger("custom_agent_logger")
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[CUSTOM_AGENT_LOGGER] %(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    custom_logger.addHandler(handler)
    custom_logger.setLevel(logging.INFO)  # Set level to INFO to show info messages
    custom_logger.propagate = False
    return custom_logger


def get_custom_team_logger():
    """Return an example custom team logger."""
    custom_logger = logging.getLogger("custom_team_logger")
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[CUSTOM_TEAM_LOGGER] %(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    custom_logger.addHandler(handler)
    custom_logger.setLevel(logging.DEBUG)  # Set level to DEBUG to show debug messages
    custom_logger.propagate = False
    return custom_logger


# Get our custom loggers. We will use one for Agents and one for Teams.
custom_agent_logger = get_custom_agent_logger()
custom_team_logger = get_custom_team_logger()

# Configure Agno to use our custom loggers.
configure_agno_logging(
    custom_default_logger=custom_agent_logger,
    custom_agent_logger=custom_agent_logger,
    custom_team_logger=custom_team_logger,
)


# Now let's setup a Team and run it.
# Logging coming from the Team will use our custom Team logger,
# while logging coming from the Agent will use our custom Agent logger.
agent = Agent()
team = Team(members=[agent])

team.run("What can I do to improve my diet?")
