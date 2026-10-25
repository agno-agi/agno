"""
This is an example of how to use the AnakinTools.

Prerequisites:
- Create an Anakin account and get an API key
- Set the API key as an environment variable:
    export ANAKIN_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.tools.anakin import AnakinTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    tools=[AnakinTools(all=True)],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Should use scrape
    agent.print_response("Scrape https://docs.agno.com/introduction/ and summarize it")

    # Should use search
    agent.print_response("Search the web for the latest on 'AI agent frameworks'")

    # Should use map
    agent.print_response("List the URLs reachable from https://docs.agno.com")
