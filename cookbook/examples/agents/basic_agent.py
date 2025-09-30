from agno.agent import Agent

agent = Agent(
    model="anthropic:claude-3-7-sonnet-latest",
    instructions="You are an agent focused on responding in one line. All your responses must be super concise and focused.",
    markdown=True,
)
agent.print_response("What is the stock price of Apple?")
