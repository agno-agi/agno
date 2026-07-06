"""
n8n Tools

Setup:
1. Generate an API key in your n8n instance:
   Settings -> API -> Create API Key
2. Set environment variables:
   - N8N_API_KEY: Your n8n API key
   - N8N_BASE_URL: Optional base URL (defaults to http://localhost:5678)
"""

from os import getenv

from agno.agent import Agent
from agno.tools.n8n import N8nTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

base_url = getenv("N8N_BASE_URL", "http://localhost:5678")

agent = Agent(
    instructions=[
        "Use n8n tools to monitor and manage workflow automations.",
        "When listing workflows, summarize their name, active status, and last update.",
        "When reporting executions, highlight any failures and suggest next steps.",
    ],
    tools=[
        N8nTools(
            base_url=base_url,
            enable_list_workflows=True,
            enable_get_workflow=True,
            enable_activate_workflow=True,
            enable_deactivate_workflow=True,
            enable_list_executions=True,
            enable_get_execution=True,
            enable_delete_execution=True,
        )
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List all workflows and their status, then show the last 5 executions and flag any failures.",
        markdown=True,
    )

    # Async variant:
    # import asyncio
    #
    # async def run_async():
    #     await agent.aprint_response(
    #         "List all active workflows and check for recent failed executions.",
    #         markdown=True,
    #     )
    #
    # asyncio.run(run_async())
