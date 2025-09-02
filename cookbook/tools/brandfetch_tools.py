"""
You can use the Brandfetch API to retrieve the company's brand information.

Register an account at: https://developers.brandfetch.com/register

For the Brand API, you can use the `brand` parameter to True. (default is True)
For the Brand Search API, you can use the `search` parameter to True. (default is False)

-- Brand API

Export your API key as an environment variable:
export BRANDFETCH_API_KEY=your_api_key

-- Brand Search API

Export your Client ID as an environment variable:
export BRANDFETCH_CLIENT_KEY=your_client_id

You can find it on https://developers.brandfetch.com/dashboard/brand-search-api in the provided URL after `c=...`

"""

import asyncio

from agno.agent import Agent
from agno.tools.brandfetch import BrandfetchTools

# Brand API

# agent = Agent(
#     tools=[BrandfetchTools()],
#     description="You are a Brand research agent. Given a company name or company domain, you will use the Brandfetch API to retrieve the company's brand information.",
# )
# agent.print_response("What is the brand information of Google?", markdown=True)


# Brand Search API

agent = Agent(
    tools=[BrandfetchTools(async_tools=True)],
    description="You are a Brand research agent. Given a company name or company domain, you will use the Brandfetch API to retrieve the company's brand information.",
)
asyncio.run(
    agent.aprint_response("What is the brand information of Agno?", markdown=True)
)
