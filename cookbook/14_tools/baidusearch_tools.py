from agno.agent import Agent
from agno.tools.baidusearch import BaiduSearchTools

agent = Agent(
    tools=[BaiduSearchTools()],
    description="You are a search agent that helps users find the most relevant information using Baidu.",
    instructions=[
        "Given a topic by the user, respond with the 3 most relevant search results about that topic.",
        "Search for 5 results and select the top 3 unique items.",
        "Search in both English and Chinese.",
    ],
)
agent.print_response("What are the latest advancements in AI?", markdown=True)
