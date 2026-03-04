"""
Include Tool Results in Member Response
========================================

Demonstrates suppressing raw tool call results as fallback content
in member responses to the supervisor. When a member agent's text
content is empty (e.g. it only ran tools), the supervisor receives
clean text instead of noisy tool output.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
web_researcher = Agent(
    name="WebResearcher",
    role="Web Research Specialist",
    tools=[DuckDuckGoTools()],
    instructions=dedent("""
        You are a web research specialist.
        - Use DuckDuckGo to find relevant information
        - Provide concise, factual summaries
    """).strip(),
)

writer = Agent(
    name="Writer",
    role="Content Writer",
    instructions=dedent("""
        You are a content writer.
        - Synthesize research into well-written summaries
        - Keep responses concise and informative
    """).strip(),
)

# ---------------------------------------------------------------------------
# Create Team with include_tool_results_in_member_response=False
# ---------------------------------------------------------------------------
research_team = Team(
    name="Research Team",
    model=OpenAIResponses(id="gpt-4o"),
    members=[web_researcher, writer],
    description="A research team that searches the web and writes summaries.",
    instructions=dedent("""
        You are a research coordinator.

        Your Process:
        1. Delegate web research to WebResearcher
        2. Delegate writing to Writer
        3. Synthesize the results

        Guidelines:
        - Always delegate research tasks to WebResearcher first
        - Then ask Writer to create a summary
        - Provide a final synthesized response
    """).strip(),
    # Suppress raw tool results from being sent back to the supervisor
    # when a member's text content is empty
    include_tool_results_in_member_response=False,
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    research_team.print_response(
        "What are the latest trends in quantum computing?",
        stream=True,
    )
