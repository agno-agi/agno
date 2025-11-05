"""Chrome DevTools MCP Agent - Advanced Browser Automation Workflow

This example demonstrates advanced browser automation workflows using the
Chrome DevTools MCP server, including form filling, multi-step navigation,
and complex user interactions.

Features demonstrated:
- Multi-step navigation workflows
- Form automation (filling, submitting)
- Element interaction (clicking, typing, dragging)
- Dialog handling (alerts, confirms, prompts)
- Screenshot capture at different stages
- Waiting for dynamic content

Run: `pip install agno mcp` to install the dependencies
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from agno.utils.pprint import apprint_run_response
from mcp import StdioServerParameters


async def browser_automation_workflow(url: str) -> None:
    """Demonstrate a complex browser automation workflow."""

    # Initialize the Chrome DevTools MCP server with custom options
    server_params = StdioServerParameters(
        command="npx",
        args=[
            "-y",
            "chrome-devtools-mcp@latest",
            # Uncomment below to run in headless mode (no visible browser window)
            # "--headless",
        ],
    )

    async with MCPTools(server_params=server_params) as mcp_tools:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[mcp_tools],
            instructions=dedent("""\
                You are an expert browser automation specialist.

                When performing automation tasks:
                1. Break down complex tasks into clear steps
                2. Wait for pages to fully load before interacting
                3. Verify elements exist before clicking or filling
                4. Handle any dialogs or popups that appear
                5. Take screenshots to document your progress
                6. Report any errors or unexpected behavior

                Always be methodical and patient with page loads and interactions.\
            """),
            markdown=True,
        )

        workflow_message = dedent("""\
            Scrape top 10 latest hacker news stories and their titles.
        """.format(url=url))

        response_stream = await agent.arun(workflow_message)
        await apprint_run_response(response_stream)


if __name__ == "__main__":
    print("=== Running Browser Automation Workflow ===\n")
    asyncio.run(browser_automation_workflow("https://news.ycombinator.com"))
