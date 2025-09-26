from agno.agent import Agent, RunOutput  # noqa
from agno.models.siliconflow import Siliconflow

agent = Agent(model=Siliconflow(id="openai/gpt-oss-120b"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Explain quantum computing in simple terms")
# print(run.content)

# Print the response in the terminal
agent.print_response("Explain quantum computing in simple terms")
