"""
Unbrowse Tools
=============================

Demonstrates Unbrowse tools for reading web pages and calling website APIs.

Unbrowse turns websites into APIs that agents can call. The toolkit can read a
page as markdown, search for learned site APIs that fit a task, run a task or a
learned API, and list a site's URLs.

Requires: UNBROWSE_API_KEY environment variable.
Get your key at https://unbrowse.ai/app

The toolkit uses `httpx`, which installs with agno. No extra dependencies are needed.
"""

from agno.agent import Agent
from agno.tools.unbrowse import UnbrowseTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Read pages (scrape_page) and list a site's URLs (map_site)
reader_agent = Agent(
    tools=[
        UnbrowseTools(
            enable_discover=False,
            enable_run_task=False,
            enable_map_site=True,
        )
    ],
    description="You are a research agent that reads web pages and summarizes them.",
    instructions=[
        "Use map_site to find the right page on a site, then scrape_page to read it.",
        "Summarize what you read and cite the URLs.",
    ],
)

# Example 2: Discover and run website APIs (scrape_page, discover, run_task)
task_agent = Agent(
    tools=[UnbrowseTools()],
    description="You are an agent that gets things done on websites through their APIs.",
    instructions=[
        "Use discover to find a learned website API for the task, then run_task with its capability id.",
        "If run_task returns status input_required, ask for or fill in the listed requirements and call it again.",
        "If no capability fits, fall back to scrape_page on a relevant URL.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    reader_agent.print_response(
        "Find the page about Agno's telemetry on https://docs.agno.com and summarize it.",
        markdown=True,
        stream=True,
    )

    task_agent.print_response(
        "Search Hacker News for stories about agent frameworks and list the top 5.",
        markdown=True,
        stream=True,
    )
