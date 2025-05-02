from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(model=OpenAIChat(id="gpt-4o"), tools=[DuckDuckGoTools(cache_results=True)], markdown=True, debug_mode=True)

# Get the response in a variable
run: RunResponse = agent.run("Share a latest news about AI")
print(run.metrics)
print("*****")
print(agent.session_metrics)

run: RunResponse = agent.run("Share a latest news about boston")
print(run.metrics)
print("*****")
print(agent.session_metrics)

# Print the response in the terminal
# agent.print_response("Share a 2 sentence horror story")
