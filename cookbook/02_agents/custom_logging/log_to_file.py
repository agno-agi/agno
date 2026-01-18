"""Example showing how to use a custom logger with Agno."""

import logging
from pathlib import Path

from agno.agent import Agent
from agno.utils.log import configure_agno_logging, log_info


def get_custom_logger():
    """Return an example custom logger."""
    custom_logger = logging.getLogger("file_logger")

    # Ensure tmp directory exists
    log_file_path = Path("tmp/log.txt")
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Use FileHandler instead of StreamHandler to write to file
    handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    custom_logger.addHandler(handler)
    custom_logger.setLevel(logging.INFO)  # Set level to INFO to show info logs
    custom_logger.propagate = False
    return custom_logger


# Get the custom logger we will use for the example.
custom_logger = get_custom_logger()

# Configure Agno to use our custom logger. It will be used for all logging.
configure_agno_logging(custom_default_logger=custom_logger)

# Every use of the logging function in agno.utils.log will now use our custom logger.
log_info("This is using our custom logger!")

# Now let's setup an Agent and run it.
# All logging coming from the Agent will use our custom logger.
agent = Agent()
agent.print_response("What can I do to improve my sleep?")
