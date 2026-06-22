"""
Research Team - Coordinated, Parallel-Powered Agents
====================================================

One agent can research a topic. A team can divide and conquer: a web
researcher gathers live sources while a deep researcher runs cited Task-API
research, and the team lead synthesizes a single answer.

Each member is backed by a different slice of the Parallel API.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.parallel import ParallelTools

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
# Fast web researcher - Search and Extract for breadth and recency.
web_researcher = Agent(
    name="Web Researcher",
    role="Find recent, relevant sources on the web using Parallel Search.",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_search=True, enable_extract=True)],
)

# Deep researcher - Task API for cited, in-depth findings.
deep_researcher = Agent(
    name="Deep Researcher",
    role="Run deep research with citations using the Parallel Task API.",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_search=False,
            enable_extract=False,
            enable_task=True,
            default_processor="base",
            default_output_schema={"type": "text"},
        )
    ],
)

# ---------------------------------------------------------------------------
# Create the Team
# ---------------------------------------------------------------------------
research_team = Team(
    name="Research Team",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[web_researcher, deep_researcher],
    instructions=[
        "Coordinate the two researchers to answer the question.",
        "Use the web researcher for breadth and current sources, and the "
        "deep researcher for cited, in-depth findings.",
        "Synthesize one clear answer and include the sources.",
    ],
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run the Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    research_team.print_response(
        "Give me a briefing on the AI web-research API landscape: who the "
        "main players are and what makes each different. Include sources.",
        stream=True,
    )
