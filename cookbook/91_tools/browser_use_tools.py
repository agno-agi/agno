"""Browser Use cloud browser agent.

Set BROWSER_USE_API_KEY (https://cloud.browser-use.com/settings?tab=api-keys)
and your agent model's credentials. The agent hands browser work to the
Browser Use Cloud agent and can continue in the same browser with session_id.
"""

from agno.agent import Agent
from agno.tools.browser_use import BrowserUseTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Web Agent",
    tools=[BrowserUseTools()],
    instructions=[
        "Use run_browser_task for anything that needs a live website.",
        "Pass session_id from the previous result to continue in the same browser.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What is the title of the top story on news.ycombinator.com right now?"
    )
