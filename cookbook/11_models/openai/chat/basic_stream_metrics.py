from typing import Iterator  # noqa
from agno.agent import Agent, RunOutputEvent  # noqa
from agno.models.openai import OpenAIChat
from agno.db.in_memory import InMemoryDb

agent = Agent(model=OpenAIChat(id="gpt-4o"), db=InMemoryDb(), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)

run_output = agent.get_last_run_output()
print("Metrics:")
print(run_output.metrics)

print("Message Metrics:")
for message in run_output.messages:
    if message.role == "assistant":
        print(message.role)
        print(message.metrics)
