"""Runnable companion to the release agent guide."""

from agno.os import AgentOS, MCPConfig
from release_agent import release_agent

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[release_agent],
    mcp=MCPConfig(
        default_tools=False,
        tools=[
            release_agent.as_tool(
                name="write_release_notes",
                description="Write and revise release notes from a list of product changes.",
            ),
        ],
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="release_mcp:app", host="127.0.0.1", port=7777)
