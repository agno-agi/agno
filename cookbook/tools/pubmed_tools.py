from agno.agent import Agent
from agno.tools.pubmed import PubmedTools

agent = Agent(tools=[PubmedTools()], show_tool_calls=True)
agent.print_response("Tell me about ulcerative colitis.")
