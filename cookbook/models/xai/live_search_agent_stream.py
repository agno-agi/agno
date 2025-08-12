from agno.agent import Agent
from agno.models.xai.xai import xAI

agent = Agent(
    model=xAI(
        id="grok-3",
        search_parameters={
            "mode": "on",
            "max_search_results": 20,
            "return_citations": True,
        },
    ),
    markdown=True,
)
agent.print_response(
    "Provide me a digest of world news in the last 24 hours.", stream=True
)
