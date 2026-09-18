"""Use Context.dev tools with an Agno agent.

Prerequisites:
- Create a Context.dev account and API key at https://context.dev
- Set CONTEXT_API_KEY in your environment
"""

from agno.agent import Agent
from agno.tools.context import ContextTools

agent = Agent(
    tools=[ContextTools(enable_sitemap=True, enable_extract=True, enable_brand=True)],
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Search for Context.dev's latest product updates and cite the source URLs.",
        stream=True,
    )
    agent.print_response(
        "Extract the plan names and prices from https://www.context.dev/pricing.",
        stream=True,
    )
