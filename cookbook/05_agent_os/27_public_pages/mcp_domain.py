"""Serve one MCP tool at a dedicated hostname and retain the native endpoint.

Run with --check to validate configuration, or without it to serve on port 8000.
Try: curl -i -H 'Host: mcp.example.com' http://127.0.0.1:8000/
"""

import argparse

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig


def documentation_home() -> str:
    """Return the documentation homepage."""
    return "https://docs.example.com"


agent = Agent(id="docs", model=OpenAIResponses(id="gpt-5.6-luna"))
agent_os = AgentOS(
    agents=[agent],
    name="Documentation MCP",
    mcp=MCPConfig(
        tools=[documentation_home],
        default_tools=False,
        stateless=True,
        root_host="mcp.example.com",
        server_card_url="https://mcp.example.com",
    ),
)
app = agent_os.get_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    if parser.parse_args().check:
        print("MCP domain configuration validated.")
    else:
        agent_os.serve("mcp_domain:app", host="127.0.0.1", port=8000, reload=False)
