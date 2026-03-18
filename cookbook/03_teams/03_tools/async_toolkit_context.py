"""
Async Toolkit Context
=====================

Demonstrates that async-only toolkit functions are correctly included
in the team system message when add_member_tools_to_context=True.
"""

from agno.agent import Agent
from agno.team import Team
from agno.team.mode import TeamMode
from agno.tools import Toolkit


# ---------------------------------------------------------------------------
# Define an async-only toolkit
# ---------------------------------------------------------------------------
class AsyncResearchTools(Toolkit):
    def __init__(self):
        super().__init__(name="async_research_tools")
        self.register(self.async_search)
        self.register(self.async_summarize)

    async def async_search(self, query: str) -> str:
        """Search for information on a topic."""
        return f"Search results for: {query}"

    async def async_summarize(self, text: str) -> str:
        """Summarize a block of text."""
        return f"Summary of: {text}"


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
research_agent = Agent(
    name="Research Agent",
    role="Research topics using async tools",
    tools=[AsyncResearchTools()],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Research Team",
    members=[research_agent],
    mode=TeamMode.coordinate,
    add_member_tools_to_context=True,
)

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # async_mode=True shows async tools (used by aget_system_message / team.arun)
    content = team.get_members_system_message_content(async_mode=True)
    print("Team system message content (async mode):")
    print(content)

    # Verify async tool names are present in async mode
    assert "async_search" in content, "async_search should appear in async team context"
    assert "async_summarize" in content, (
        "async_summarize should appear in async team context"
    )
    print("PASS: Async toolkit functions are visible in the team system message.")
