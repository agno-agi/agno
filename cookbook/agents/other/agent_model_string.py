from agno.agent import Agent    

agent = Agent(model="openai:gpt-4o", markdown=True)

agent.print_response("Share a 2 sentence horror story")
