from agno.agent import Agent, RunOutput  # noqa

agent = Agent(model="groq:llama-3.3-70b-versatile", markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response on the terminal
agent.print_response("Share a 2 sentence horror story")
