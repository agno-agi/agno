"""
Sleep Tools
=============================

Demonstrates sleep tools.
"""

from agno.agent import Agent
from agno.tools.sleep import SleepTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Enable specific sleep functions
agent = Agent(tools=[SleepTools(enable_sleep=True)], name="Sleep Agent")

# Example 2: Enable all sleep functions
agent_all = Agent(tools=[SleepTools(all=True)], name="Full Sleep Agent")

# Test the agents

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Sleep for 2 seconds")
    agent_all.print_response("Sleep for 5 seconds")
