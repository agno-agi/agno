from agno.agent import Agent, RunOutputEvent  # noqa
from agno.models.siliconflow import Siliconflow

agent = Agent(model=Siliconflow(id="openai/gpt-oss-120b"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Explain quantum computing in simple terms", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Explain quantum computing in simple terms", stream=True)
