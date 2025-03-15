from agno.agent import Agent
from agno.tools.bingsearch import BingSearchTools

"""
To create Azure Bing Search v7 service and get subscription key, 
follow the instruction (https://learn.microsoft.com/en-us/bing/search-apis/bing-web-search/create-bing-search-service-resource)
"""

BINGSEARCH_SUBSCRIPTION_KEY = "<YOUR_BINGSEARCH_SUBSCRIPTION_KEY>"

agent = Agent(
    tools=[
        BingSearchTools(
            subscription_key=BINGSEARCH_SUBSCRIPTION_KEY
        )
    ],
    show_tool_calls=True,
)
agent.print_response("Whats happening in Belgium?", markdown=True)
