from agno.agent import Agent, RunResponse  # noqa
from agno.models.siliconflow import Siliconflow

agent = Agent(model=Siliconflow(id="Qwen/Qwen3-8B"), markdown=True)

# Get the response in a variable
# run: RunResponse = agent.run("Explain quantum computing in simple terms")
# print(run.content)

# Print the response in the terminal
agent.print_response("Explain quantum computing in simple terms")
