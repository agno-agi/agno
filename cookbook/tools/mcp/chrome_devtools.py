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

from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from agno.os import AgentOS
from mcp import StdioServerParameters
from agno.db.postgres import PostgresDb


db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

# Initialize the Chrome DevTools MCP server with custom options
browser_server_params = StdioServerParameters(
    command="npx",
    args=[
        "-y",
        "chrome-devtools-mcp@latest",
        # Uncomment below to run in headless mode (no visible browser window)
        # "--headless",
    ],
)

performance_server_params = StdioServerParameters(
    command="npx",
    args=[
        "-y",
        "chrome-devtools-mcp@latest",
        # "--headless",
    ],
)

# Create Browser Automation Agent
agent_browser = Agent(
    name="Browser Automation Agent",
    role="Expert browser automation specialist",
    id="browser_agent",
    db=db,
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[MCPTools(server_params=browser_server_params)],
    instructions=dedent("""\
        You are an expert browser automation specialist.

        don't take screenshots for now

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

# Create Performance Analysis Agent
agent_performance = Agent(
    name="Performance Analysis website",
    role="Expert website performance analyst",
    id="performance_website_agent",
    db=db,
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[MCPTools(server_params=performance_server_params)],
    markdown=True,
    instructions=dedent("""\
        You are an expert website performance analyst.

        don't take screenshots for now.

        When analyzing websites:
        1. Navigate to the target URL
        2. Measure key performance metrics (LCP, FCP, etc.)
        3. Identify the slowest resources on the page
        4. Provide actionable recommendations for improvement
        5. Document findings with screenshots if helpful

        Focus on Core Web Vitals and user experience metrics.\
    """),
)

# Create the AgentOS
agent_os = AgentOS(
    id="chrome-devtools-agentos",
    agents=[agent_browser, agent_performance],
)

app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="chrome_devtools:app", port=7777, reload=True)