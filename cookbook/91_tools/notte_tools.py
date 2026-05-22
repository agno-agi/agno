"""
Notte Tools
=============================

Demonstrates Notte browser tools for Agno agents.
"""

from agno.agent import Agent
from agno.tools.notte import NotteTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Notte Configuration
# -------------------------------
# These environment variables drive the NotteTools.
# Set them in your .env file or export them in your shell.

# NOTTE_API_KEY: Your API key from the Notte console
#   - Required for authentication
#   - Get one at https://console.notte.cc

# NOTTE_API_URL: Notte API endpoint
#   - Optional. Defaults to https://api.notte.cc.
#   - Override only for self-hosted deployments or non-default regions.

# ==================== Usage ====================
# NotteTools automatically picks the right implementation based on context:
# - Sync tools when using agent.run() or agent.print_response()
# - Async tools when using agent.arun() or agent.aprint_response()

agent = Agent(
    name="Web Automation Assistant",
    tools=[NotteTools()],
    instructions=[
        "You are a web automation assistant powered by Notte. You can help with:",
        "1. Filling forms and clicking through multi-step web flows",
        "2. Extracting clean markdown or structured data from web pages",
        "3. Capturing screenshots of websites",
        "4. Monitoring website changes",
        "5. Delegating complex multi-step browsing to an autonomous browser agent when a task is too open-ended for step-by-step tool use",
        "Note: call observe before click or fill to discover the current interactive element IDs (B1, I1, L1, ...).",
    ],
    markdown=True,
)

# ==================== Sync Usage ====================
# Use this for regular scripts and synchronous execution.

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("""
        Visit https://quotes.toscrape.com and:
        1. Extract the first 5 quotes and their authors
        2. Navigate to page 2
        3. Extract the first 5 quotes from page 2
    """)

    # ==================== Async Usage ====================
    # Use this for FastAPI, async frameworks, or when using agent.arun().
    # The same agent instance works for both sync and async; just use arun/aprint_response.

    # import asyncio
    #
    #
    # async def main():
    #     await agent.aprint_response("""
    #         Visit https://quotes.toscrape.com and:
    #         1. Extract the first 5 quotes and their authors
    #         2. Navigate to page 2
    #         3. Extract the first 5 quotes from page 2
    #     """)
    #
    #
    # if __name__ == "__main__":
    #     asyncio.run(main())
