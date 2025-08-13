from agno.agent import Agent
from agno.models.anthropic import Claude

agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    instructions="You are an agent focused on responding in one line. All your responses must be super concise and focused.",
    markdown=True,
)
runx = agent.run("What is the stock price of Apple?")
