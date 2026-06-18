"""
Dependencies Merge — Dojo Demo
==============================

Agent with backend dependencies that merge with frontend context.

Backend dependencies (api_version, feature_flags) are set at agent creation.
Frontend sends context via useAgentContext hook (user_name, current_page).
SDK merges both automatically — frontend values win on key conflicts.
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

When asked about dependencies or context, list everything in <additional context> tags:
- Backend: api_version, feature_flags, server_region
- Frontend: user_name, current_page, cart_data, etc.

Format as a clear list showing each value.""",
    markdown=True,
)
