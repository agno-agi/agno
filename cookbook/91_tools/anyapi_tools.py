"""
This is an example of how to use the AnyAPITools.

AnyAPI is a unified marketplace for scraping and data APIs: any API, one wallet, USD, no
subscriptions. Reach hundreds of third-party APIs (social media, search results, web data)
through one key and one normalized interface; pay per request in real dollars; failed calls
are never charged - AnyAPI fails over across providers automatically under one price.

Prerequisites:
- Install the AnyAPI SDK: pip install getanyapi
- Get an API key at https://getanyapi.com/dashboard. New accounts start with free trial credit.
- Set the API key as an environment variable:
    export ANYAPI_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.tools.anyapi import AnyAPITools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    tools=[AnyAPITools(enable_get_balance=True)],
    instructions=[
        "Find an API with search_apis, read its input schema and USD price with get_api, then run it with run_api.",
        "Build the input from the schema get_api returns. Every input schema is strict.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Should search the catalog and run the API it finds
    agent.print_response("Get the top Google search results for 'agno agent framework'")

    # Should report the wallet balance
    agent.print_response("How much USD is left on my AnyAPI wallet?")
