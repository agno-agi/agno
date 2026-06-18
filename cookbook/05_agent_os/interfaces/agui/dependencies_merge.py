"""
Dependencies Merge — Dojo Demo
==============================

Agent with backend dependencies that merge with UI-sent context.

The agent has backend dependencies (api_version, feature_flags) configured at creation.
The frontend sends context via useAgentContext (user_name, current_page, cart_data).
The SDK merges both automatically — UI values win on key conflicts.

Dojo sends context via useAgentContext hook:
{
    description: "user_name",
    value: "Alice"
}

This becomes a flat dependency: {"user_name": "Alice"}
JSON string values are parsed back to structured data automatically.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses

dependencies_agent = Agent(
    name="dependencies_merge",
    model=OpenAIResponses(id="gpt-5.5"),
    dependencies={
        "api_version": "v2.1",
        "feature_flags": {"dark_mode": True, "beta_features": False},
        "server_region": "us-east-1",
    },
    add_dependencies_to_context=True,
    instructions="""You help users understand what context is available to you.

When asked about dependencies or context, list everything you see in <additional context> tags:
- Backend dependencies: api_version, feature_flags, server_region
- Frontend context: user_name, current_page, cart_data, etc.

Format your response as a clear list showing each value.""",
    markdown=True,
)
