from agno.agent import Agent
from agno.tools.zendesk import ZendeskTools

agent = Agent(tools=[ZendeskTools()])
agent.print_response("How do I login?", markdown=True)
