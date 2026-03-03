"""
Newspaper4K Tools
=============================

Demonstrates newspaper4k tools.
"""

from agno.agent import Agent
from agno.tools.newspaper4k import Newspaper4kTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(tools=[Newspaper4kTools(enable_read_article=True)])

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Please summarize https://www.rockymountaineer.com/blog/experience-icefields-parkway-scenic-drive-lifetime"
    )
